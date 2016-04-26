#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2016, 2016, Oracle and/or its affiliates. All rights reserved.
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

import json
import re
import socket
import subprocess
import traceback
import uuid
from argparse import ArgumentParser

import mx


_bm_suites = {}


class BenchmarkSuite(object):
    def name(self):
        """Returns the name of the suite.

        :return: Name of the suite.
        :rtype: str
        """
        raise NotImplementedError()

    def group(self):
        """The group that this benchmark suite belongs to, for example, `Graal`.

        This is the name of the overall group of closely related projects.

        :return: Name of the group.
        :rtype: str
        """
        raise NotImplementedError()

    def subgroup(self):
        """The subgroup that this suite belongs to, e.g., `fastr` or `graal-compiler`.

        This is the name of the subteam project within the group.

        :return: Name of the subgroup.
        :rtype: str
        """
        raise NotImplementedError()

    def benchmarks(self):
        """Returns the list of the benchmarks provided by this suite.

        :return: List of benchmark string names.
        :rtype: list
        """
        raise NotImplementedError()

    def validateEnvironment(self):
        """Validates the environment and raises exceptions if validation fails.

        Can be overridden to check for existence of required environment variables
        before the benchmark suite executed.
        """
        pass

    def vmArgs(self, bmSuiteArgs):
        """Extracts the VM flags from the list of arguments passed to the suite.

        :param list bmSuiteArgs: List of string arguments to the suite.
        :return: A list of string flags that are VM flags.
        :rtype: list
        """
        raise NotImplementedError()

    def runArgs(self, bmSuiteArgs):
        """Extracts the run flags from the list of arguments passed to the suite.

        :param list bmSuiteArgs: List of string arguments to the suite.
        :return: A list of string flags that are arguments for the suite.
        :rtype: list
        """
        raise NotImplementedError()

    def before(self, bmSuiteArgs):
        """Called exactly once before any benchmark invocations begin.

        Useful for outputting information such as platform version, OS, etc.

        Arguments: see `run`.
        """
        pass

    def run(self, benchmarks, bmSuiteArgs):
        """Runs the specified benchmarks with the given arguments.

        More precisely, if `benchmarks` is a list, runs the list of the benchmarks from
        the suite in one run (typically, one VM invocations). If `benchmarks` is None,
        then it runs all the benchmarks from the suite.

        .. note:: A benchmark suite may not support running multiple benchmarks,
                  or None, but it must at least run with a single benchmark in the
                  `benchmarks` list.

        :param benchmarks: List of benchmark string names, or a None.
        :type benchmarks: list or None
        :param list bmSuiteArgs: List of string arguments to the suite.
        :return:
            A dictionary of measurement results.

            A measurement result is an object that can be converted into JSON and is
            merged with the other dimensions of the data point.

            A measurement result must contain a field `metric`, which has the following
            values:
                - `metric.name` -- name of the metric (e.g. `"time"`, `"memory"`, ...)
                - `metric.value` -- value of the measurement (e.g. `1.54`)
                - `metric.unit` -- a string that specified the unit of measurement
                  (e.g. `"ms"`)
                - `metric.score-function` -- name of the scoring function for the result
                  (e.g. `id`, which just returns the measurement value)
                - `metric.score-value` -- score of the value, evaluated by the specified
                  scoring function (e.g. `"1.54"`)
                - `metric.type` -- a string denoting the type of the metric
                  (e.g. `"numeric"`)
                - `metric.better` -- `"higher"` if higher is better, `"lower"` otherwise
                - `metric.iteration` -- iteration number of the measurement (e.g. `0`)
        :rtype: object
        """
        raise NotImplementedError()


def add_bm_suite(suite):
    if suite.name() in _bm_suites:
        raise RuntimeError("Benchmark suite '{0}' already exists.".format(suite.name()))
    _bm_suites[suite.name()] = suite


class StdOutRule(object):
    """Each rule contains a parsing pattern and a replacement template.

    A parsing pattern is a regex that may contain any number of named groups,
    as shown in the example:

        r"===== DaCapo (?P<benchmark>[a-z]+) PASSED in (?P<value>[0-9]+) msec ====="

    The above parsing regex captures the benchmark name into a variable `benchmark`
    and the elapsed number of milliseconds into a variable called `value`.

    A replacement template is a dictionary that describes how to create a measurement:

        {
          "benchmark": ("<benchmark>", str),
          "metric.name": "time",
          "metric.value": ("<value>", int),
          "metric.unit": "ms",
          "metric.score-function": "id",
          "metric.type": "numeric",
          "metric.better": "lower",
          "metric.iteration": ("$iteration", id),
        }

    When `instantiate` is called, the tuples in the template shown above are
    replaced with the corresponding named groups from the parsing pattern, and converted
    to the specified type.

    Tuples can contain one of the following special variables, prefixed with a `$` sign:
        - `iteration` -- ordinal number of the match that produced the datapoint, among
          all the matches for that parsing rule.
    """

    def __init__(self, pattern, replacement):
        self.pattern = pattern
        self.replacement = replacement

    def parse(self, text):
        datapoints = []
        capturepat = re.compile(r"<([a-zA-Z_][0-9a-zA-Z_]*)>")
        varpat = re.compile(r"\$([a-zA-Z_][0-9a-zA-Z_]*)")
        for iteration, m in enumerate(re.finditer(self.pattern, text, re.MULTILINE)):
            datapoint = {}
            for key, value in self.replacement.iteritems():
                inst = value
                if isinstance(inst, tuple):
                    v, vtype = inst
                    # Instantiate with named captured groups.
                    def var(name):
                        if name == "iteration":
                            return str(iteration)
                        else:
                            raise RuntimeError("Unknown var {0}".format(name))
                    v = varpat.sub(lambda vm: var(vm.group(1)), v)
                    v = capturepat.sub(lambda vm: m.groupdict()[vm.group(1)], v)
                    # Convert to a different type.
                    if vtype is str:
                        inst = str(v)
                    elif vtype is int:
                        inst = int(v)
                    elif vtype is float:
                        inst = float(v)
                    elif vtype is bool:
                        inst = bool(v)
                    else:
                        raise RuntimeError("Cannot handle type {0}".format(vtype))
                if type(inst) not in [str, int, float, bool]:
                    raise RuntimeError("Object has unknown type: {0}".format(inst))
                datapoint[key] = inst
            datapoints.append(datapoint)
        return datapoints


class StdOutBenchmarkSuite(BenchmarkSuite):
    """Convenience suite for benchmarks that need to parse standard output.

    The standard output benchmark proceeds in the following steps:

    1. Run the benchmark.
    2. Terminate if there was a non-zero exit code.
    3. Terminate if one of the specified failure patterns was matched.
    4. Terminate if none of the specified success patterns was matched.
    5. Use the parse rules on the standard output to create data points.
    """
    def run(self, benchmarks, bmSuiteArgs):
        retcode, out = self.runAndReturnStdOut(benchmarks, bmSuiteArgs)
        return self.validateStdout(out, benchmarks, bmSuiteArgs, retcode=retcode)

    def validateStdout(self, out, benchmarks, bmSuiteArgs, retcode=None):
        """Validate out against the parse rules and create data points.
        Subclass may override to customize validation.
        """
        def compiled(pat):
            if type(pat) is str:
                return re.compile(pat)
            return pat
        flaky = False
        for pat in self.flakySuccessPatterns():
            if compiled(pat).match(out):
                flaky = True
        if not flaky:
            if retcode:
                if not self.validateReturnCode(retcode):
                    raise RuntimeError(
                        "Benchmark failed, exit code: {0}".format(retcode))
            for pat in self.failurePatterns():
                if compiled(pat).match(out):
                    raise RuntimeError("Benchmark failed")
            success = False
            for pat in self.successPatterns():
                if not compiled(pat).match(out):
                    success = True
            if not success:
                raise RuntimeError("Benchmark failed")

        datapoints = []
        for rule in self.rules(out, benchmarks, bmSuiteArgs):
            datapoints.extend(rule.parse(out))
        return datapoints

    def validateReturnCode(self, retcode):
        return retcode is 0

    def flakySuccessPatterns(self):
        """List of regex pattern that can override matched failure and success patterns.

        If any of the patterns in this list match, the output will not be checked for
        failure or success patterns.
        If none of the patterns in this list match, the output is checked normally.

        This method should be overridden for suites that are known to be flaky.
        """
        return []

    def failurePatterns(self):
        """List of regex patterns which fail the benchmark when matched."""
        return []

    def successPatterns(self):
        """List of regex patterns which fail the benchmark if not matched."""
        return []

    def rules(self, output, benchmarks, bmSuiteArgs):
        """Returns a list of rules required to parse the standard output.

        :param string output: Contents of the standard output.
        :param list benchmarks: List of benchmarks that were run.
        :param list bmSuiteArgs: Arguments to the benchmark suite (after first `--`).
        :return: List of StdOutRule parse rules.
        :rtype: list
        """
        raise NotImplementedError()

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        """Runs the benchmarks and returns a string containing standard output.

        See arguments `run`.

        :return: The return code, and a standard output string
        :rtype: tuple
        """
        raise NotImplementedError()


class JavaBenchmarkSuite(StdOutBenchmarkSuite): #pylint: disable=R0922
    """Convenience suite used for benchmarks running on the JDK.
    """
    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        """Creates a list of arguments for the JVM using the suite arguments.

        :param list benchmarks: List of benchmarks from the suite to execute.
        :param list bmSuiteArgs: Arguments passed to the suite.
        """
        raise NotImplementedError()

    def workingDirectory(self, benchmarks, bmSuiteArgs):
        """Returns the desired working directory for running the benchmark.

        By default it returns `None`, meaning that the working directory is not be
        changed. It is meant to be overridden in subclasses when necessary.
        """
        return None

    def before(self, bmSuiteArgs):
        mx.log("Running on JVM with -version:")
        mx.get_jdk().run_java(["-version"], nonZeroIsFatal=False)

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        jdk = mx.get_jdk()
        out = mx.TeeOutputCapture(mx.OutputCapture())
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        args = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        if args is None:
            return 0, ""
        mx.log("Running JVM with args: {0}.".format(args))
        exitCode = jdk.run_java(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)
        return exitCode, out.underlying.data


class TestBenchmarkSuite(JavaBenchmarkSuite):
    """Example suite used for testing and as a subclassing template.
    """
    def name(self):
        return "test"

    def validateReturnCode(self, retcode):
        return True

    def vmArgs(self, bmSuiteArgs):
        return []

    def runArgs(self, bmSuiteArgs):
        return []

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        return bmSuiteArgs

    def benchmarks(self):
        return ["simple-bench", "complex-bench"]

    def rules(self, out, benchmarks, bmSuiteArgs):
        return [
          StdOutRule(r"-d(?P<flag>[0-9]+)\s+use a (?P<bitnum>[0-9]+)-bit data model", {
            "input": ("<flag>", int),
            "metric.value": ("<bitnum>", int),
          }),
        ]


add_bm_suite(TestBenchmarkSuite())


class BenchmarkExecutor(object):
    def uid(self):
        return str(uuid.uuid1())

    def group(self, suite):
        return suite.group()

    def buildFlags(self):
        return ""

    def machineArch(self):
        return mx.get_arch()

    def machineCpuCores(self):
        return mx.cpu_count()

    def machineHostname(self):
        return socket.gethostname()

    def machineName(self, mxBenchmarkArgs):
        if mxBenchmarkArgs.machine_name:
            return mxBenchmarkArgs.machine_name
        return mx.get_env("MACHINE_NAME", default="")

    def machineOs(self):
        return mx.get_os()

    def commitRev(self):
        sha1 = subprocess.check_output(["git", "rev-parse", "HEAD"])
        return sha1.strip()

    def commitRepoUrl(self):
        url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"])
        return url.strip()

    def commitAuthor(self):
        out = subprocess.check_output(["git", "--no-pager", "show", "-s",
            "--format=%an", "HEAD"])
        return out.strip()

    def commitAuthorTimestamp(self):
        out = subprocess.check_output(["git", "--no-pager", "show", "-s",
            "--format=%at", "HEAD"])
        return int(out.strip())

    def commitCommitter(self):
        out = subprocess.check_output(["git", "--no-pager", "show", "-s",
            "--format=%cn", "HEAD"])
        return out.strip()

    def commitCommitTimestamp(self):
        out = subprocess.check_output(["git", "--no-pager", "show", "-s",
            "--format=%ct", "HEAD"])
        return int(out.strip())

    def branch(self):
        out = subprocess.check_output(["git", "name-rev", "--name-only", "HEAD"])
        return out.strip()

    def buildUrl(self):
        return mx.get_env("BUILD_URL", default="")

    def buildNumber(self):
        return mx.get_env("BUILD_NUMBER", default="")

    def checkEnvironmentVars(self):
        pass

    def dimensions(self, suite, mxBenchmarkArgs, bmSuiteArgs):
        return {
          "metric.uuid": self.uid(),
          "group": self.group(suite),
          "subgroup": suite.subgroup(),
          "bench-suite": suite.name(),
          "config.vm-flags": " ".join(suite.vmArgs(bmSuiteArgs)),
          "config.run-flags": " ".join(suite.runArgs(bmSuiteArgs)),
          "config.build-flags": self.buildFlags(),
          "machine.name": self.machineName(mxBenchmarkArgs),
          "machine.hostname": self.machineHostname(),
          "machine.arch": self.machineArch(),
          "machine.cpu-cores": self.machineCpuCores(),
          "commit.rev": self.commitRev(),
          "commit.repo-url": self.commitRepoUrl(),
          "commit.author": self.commitAuthor(),
          "commit.author-ts": self.commitAuthorTimestamp(),
          "commit.committer": self.commitCommitter(),
          "commit.committer-ts": self.commitCommitTimestamp(),
          "branch": self.branch(),
          "build.url": self.buildUrl(),
          "build.number": self.buildNumber(),
        }

    def getSuiteAndBenchNames(self, args):
        argparts = args.benchmark.split(":")
        suitename = argparts[0]
        if len(argparts) == 2:
            benchspec = argparts[1]
        else:
            benchspec = ""
        suite = _bm_suites.get(suitename)
        if not suite:
            mx.abort("Cannot find benchmark suite '{0}'.".format(suitename))
        if benchspec is "*":
            return (suite, [[b] for b in suite.benchmarks()])
        elif benchspec is "":
            return (suite, [None])
        elif not benchspec in suite.benchmarks():
            mx.abort("Cannot find benchmark '{0}' in suite '{1}'.".format(
                benchspec, suitename))
        else:
            return (suite, [[benchspec]])

    def execute(self, suite, benchnames, mxBenchmarkArgs, bmSuiteArgs):
        def postProcess(results):
            processed = []
            for result in results:
                if not isinstance(result, dict):
                    result = result.__dict__
                point = self.dimensions(suite, mxBenchmarkArgs, bmSuiteArgs)
                point.update(result)
                processed.append(point)
            return processed

        results = suite.run(benchnames, bmSuiteArgs)
        processedResults = postProcess(results)
        return processedResults

    def benchmark(self, mxBenchmarkArgs, bmSuiteArgs):
        """Run a benchmark suite."""
        parser = ArgumentParser(prog="mx benchmark", description=benchmark.__doc__)
        parser.add_argument(
            "benchmark", help="Benchmark to run, format: <suite>:<benchmark>.")
        parser.add_argument(
            "--results-file", help="Path to JSON output file with benchmark results.")
        parser.add_argument(
            "--machine-name", default=None, help="Abstract name of the target machine.")
        mxBenchmarkArgs = parser.parse_args(mxBenchmarkArgs)

        self.checkEnvironmentVars()

        suite, benchNamesList = self.getSuiteAndBenchNames(mxBenchmarkArgs)

        results = []

        failures_seen = False
        suite.before(bmSuiteArgs)
        for benchnames in benchNamesList:
            suite.validateEnvironment()
            try:
                partialResults = self.execute(
                    suite, benchnames, mxBenchmarkArgs, bmSuiteArgs)
                results.extend(partialResults)
            except RuntimeError:
                failures_seen = True
                mx.log(traceback.format_exc())

        topLevelJson = {
          "queries": results
        }
        dump = json.dumps(topLevelJson)
        with open(mxBenchmarkArgs.results_file, "w") as txtfile:
            txtfile.write(dump)
        if failures_seen:
            return 1
        return 0


_benchmark_executor = BenchmarkExecutor()


def splitArgs(args, separator):
    """Splits the list of string arguments at the first separator argument.

    :param list args: List of arguments.
    :param str separator: Argument that is considered a separator.
    :return: A tuple with the list of arguments before and a list after the separator.
    :rtype: tuple
    """
    before = args
    after = []
    try:
        idx = args.index("--")
        before = args[:idx]
        after = args[(idx + 1):]
    except ValueError:
        pass
    return before, after


def benchmark(args):
    """Run benchmark suite.

    :Example:

        mx benchmark bmSuiteName[:benchName] [mxBenchmarkArgs] -- [bmSuiteArgs]
        mx benchmark --help

    :param list args:
        List of arguments (see below).

        `bmSuiteName`: Benchmark suite name (e.g. `dacapo`, `octane`, `specjvm08`, ...).
        `benchName`: Name of particular benchmar within the benchmark suite
            (e.g. `raytrace`, `deltablue`, `avrora`, ...), or a wildcard indicating that
            all the benchmarks need to be executed as separate runs. If omitted, all the
            benchmarks must be executed as part of one run.
        `mxBenchmarkArgs`: Optional arguments to the `mx benchmark` command.

            --results-file: Path to the file into which to dump the benchmark results.
            --machine-name: Abstract name of a machine with specific capabilities
                            (e.g. `x52`).

    Note that arguments to `mx benchmark` are separated with double dashes (`--`).
    Everything before the first `--` is passed to the `mx benchmark` command directly.
    Arguments after the `--` are passed to the specific benchmark suite, and they can
    include additional, benchmark-specific `--` occurrences.

    Examples:
        mx benchmark dacapo:avrora --results-file ./results.json -- \\
          -jar dacapo-9.12-bach.jar
        mx benchmark octane:richards -p ./results.json -- -XX:+PrintGC -- --iters=10
        mx benchmark dacapo:* --results-file ./results.json --
        mx benchmark specjvm --results-file ./output.json
    """
    mxBenchmarkArgs, bmSuiteArgs = splitArgs(args, "--")
    return _benchmark_executor.benchmark(mxBenchmarkArgs, bmSuiteArgs)
