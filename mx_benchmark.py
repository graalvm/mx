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
import uuid
from argparse import ArgumentParser

import mx


_bm_suites = {}


class BenchmarkSuite(object):
    def name(self):
        """Returns the name of the suite.

        Returns:
            basestring: Name of the suite.
        """
        raise NotImplementedError()

    def benchmarks(self):
        """Returns the list of the benchmarks provided by this suite.

        Returns:
            list of strings: List of benchmarks.
        """
        raise NotImplementedError()

    def extraDimensions(self, benchmark, vmargs, runargs):
        """Returns dictionary of extra dimensions for the given benchmark and arguments.

        Arguments:
            benchmark (string): Name of the benchmark.
            vmargs (list of strings): List of VM arguments.
            runargs (list of strings): List of benchmark arguments.

        Returns:
            dict[basestring, T]: Dictionary of field-name/value pairs.
        """
        raise NotImplementedError()

    def run(self, benchmarks, vmargs, runargs):
        """Runs the specified benchmarks with the given arguments.

        Arguments:
            benchmarks (list of strings): List of benchmark names.
            vmargs (list of strings): List of VM arguments.
            runargs (list of strings): List of benchmark arguments.

        Returns:
            object: A list of measurement results.

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
          "metric.iteration": ("<:iteration>", id),
        }

    When `instantiate` is called, the tuples in the template shown above are
    replaced with the corresponding named groups from the parsing pattern, and converted
    to the specified type.
    """

    def __init__(self, pattern, replacement):
        self.pattern = pattern
        self.replacement = replacement

    def parse(self, text):
        datapoints = []
        capturepat = re.compile(r"<([a-zA-Z_][0-9a-zA-Z_]*)>")
        varpat = re.compile(r"<:([a-zA-Z_][0-9a-zA-Z_]*)>")
        for iteration, m in enumerate(re.finditer(self.pattern, text)):
            datapoint = {}
            for key, value in self.replacement.iteritems():
                inst = value
                if isinstance(inst, tuple):
                    v, tp = inst
                    # Instantiate with named captured groups.
                    def var(name):
                        if name is "iteration":
                            return iteration
                        else:
                            raise RuntimeError("Unknown var {0}".format(name))
                    v = varpat.sub(lambda vm: var(vm.group(1)), v)
                    v = capturepat.sub(lambda vm: m.groupdict()[vm.group(1)], v)
                    # Convert to a different type.
                    if tp is str:
                        inst = str(v)
                    elif tp is int:
                        inst = int(v)
                    elif tp is float:
                        inst = float(v)
                    elif tp is bool:
                        inst = bool(v)
                    else:
                        raise RuntimeError("Cannot handle type {0}".format(tp))
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
    def run(self, benchmarks, vmargs, runargs):
        retcode, out = self.runAndReturnStdOut(benchmarks, vmargs, runargs)
        if not self.validateReturnCode(retcode):
            return {}
        for pat in self.failurePatterns():
            if pat.match(out):
                return {}
        for pat in self.successPatterns():
            if not pat.match(out):
                return {}

        datapoints = []
        for rule in self.rules(out):
            datapoints.extend(rule.parse(out))
        return datapoints

    def validateReturnCode(self, retcode):
        return retcode is 0

    def failurePatterns(self):
        """List of regex patterns which fail the benchmark when matched."""
        return []

    def successPatterns(self):
        """List of regex patterns which fail the benchmark if not matched."""
        return []

    def rules(self, output):
        """Returns a list of rules required to parse the standard output.

        Arguments:
            output (string): Contents of the standard output.

        Returns:
            [StdOutRule]: List of parse rules.
        """
        raise NotImplementedError()

    def runAndReturnStdOut(self, benchmarks, vmargs, runargs):
        """Runs the benchmarks and returns a string containing standard output.

        Returns:
            tuple: The return code and a standard output string.
        """
        raise NotImplementedError()


class JavaBenchmarkSuite(StdOutBenchmarkSuite):
    """Convenience suite used for benchmarks running on the JDK.
    """
    def defaultVmArgs(self):
        """Default VM arguments applied after the benchmark-specific ones."""
        raise NotImplementedError()

    def extraDimensions(self, benchmark, vmargs, runargs):
        return {}

    def runAndReturnStdOut(self, benchmarks, vmargs, runargs):
        jdk = mx.get_jdk()
        out = mx.OutputCapture()
        exitCode = jdk.run_java(vmargs + self.defaultVmArgs() + runargs,
            out=out, err=out, nonZeroIsFatal=False)
        return exitCode, out.data


class TestBenchmarkSuite(JavaBenchmarkSuite):
    """Example suite used for testing and as a subclassing template.
    """
    def name(self):
        return "test"

    def validateReturnCode(self, retcode):
        return True

    def benchmarks(self):
        return ["simple-bench", "complex-bench"]

    def rules(self, out):
        return [
          StdOutRule("-d(?P<flag>[0-9]+)\s+use a (?P<bitnum>[0-9]+)-bit data model", {
            "input": ("<flag>", int),
            "metric.value": ("<bitnum>", int),
          }),
        ]

    def defaultVmArgs(self):
        return []


add_bm_suite(TestBenchmarkSuite())


class BenchmarkExecutor(object):
    def uid(self):
        return str(uuid.uuid1())

    def group(self):
        return mx.get_env("GROUP")

    def subgroup(self):
        return mx.primary_suite().name

    def buildFlags(self):
        return ""

    def machineArch(self):
        return mx.get_arch()

    def machineCpuCores(self):
        return mx.cpu_count()

    def machineHostname(self):
        return socket.gethostname()

    def machineName(self):
        return mx.get_env("MACHINE_NAME")

    def machineOs(self):
        return mx.get_os()

    def commitRev(self):
        sha1 = subprocess.check_output(["git", "rev-parse", "HEAD"])
        return sha1.strip()

    def commitRepoUrl(self):
        url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"])
        return url.strip()

    def commitAuthor(self):
        url = subprocess.check_output(["git", "show", "--format=%aN", "HEAD"])
        return url.strip()

    def commitAuthorTimestamp(self):
        url = subprocess.check_output(["git", "show", "--format=%at", "HEAD"])
        return int(url.strip())

    def commitCommitter(self):
        url = subprocess.check_output(["git", "show", "--format=%aN", "HEAD"])
        return url.strip()

    def commitCommitTimestamp(self):
        url = subprocess.check_output(["git", "show", "--format=%at", "HEAD"])
        return int(url.strip())

    def branch(self):
        url = subprocess.check_output(["git", "name-rev", "--name-only", "HEAD"])
        return url.strip()

    def buildUrl(self):
        return mx.get_env("BUILD_URL")

    def buildNumber(self):
        return mx.get_env("BUILD_NUMBER")

    def dimensions(self, suite, benchname, args):
        return {
          "metric.uuid": self.uid(),
          "group": self.group(),
          "subgroup": self.subgroup(),
          "bench-suite": suite.name(),
          "benchmark": benchname,
          "config.vm-flags": " ".join(args.vmargs) if args.vmargs else "",
          "config.run-flags": " ".join(args.runargs) if args.runargs else "",
          "config.build-flags": self.buildFlags(),
          "machine.name": self.machineName(),
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
        suitename, benchnames = args.benchmark.split(":")
        suite = _bm_suites.get(suitename)
        if not suite:
            mx.abort("Cannot find benchmark suite '{0}'.".format(suitename))
        benchmarks = suite.benchmarks()
        if not benchnames in benchmarks and benchnames is not "*":
            mx.abort("Cannot find benchmark '{0}' in suite '{1}'.".format(
                benchnames, suitename))
        if benchnames is "*":
            benchnames = benchmarks
        else:
            benchnames = [benchnames]
        return suite, benchnames

    def execute(self, suite, benchnames, args):
        def postProcess(results):
            processed = []
            for result in results:
                if not isinstance(result, dict):
                    result = result.__dict__
                point = self.dimensions(suite, benchnames, args)
                point.update(result)
                processed.append(point)
            return processed

        results = suite.run(benchnames, args.vmargs, args.runargs)
        processedResults = postProcess(results)
        return processedResults

    def benchmark(self, args):
        """Run a benchmark suite."""
        parser = ArgumentParser(prog="mx benchmark", description=benchmark.__doc__)
        parser.add_argument(
            "benchmark", help="Benchmark to run, format: <suite>:<benchmark>.")
        parser.add_argument(
            "--vmargs", help="VM arguments to pass to the benchmark.", default=[])
        parser.add_argument(
            "--runargs", help="Run arguments to pass to the benchmark.", default=[])
        parser.add_argument(
            "-p", "--path", help="Path to the output file.")
        args = parser.parse_args(args)

        suite, benchnames = self.getSuiteAndBenchNames(args)

        results = self.execute(suite, benchnames, args)
        dump = json.dumps(results)
        with open(args.path, "w") as txtfile:
          txtfile.write(dump)


_benchmark_executor = BenchmarkExecutor()


def benchmark(args):
    """Run benchmark suite."""
    _benchmark_executor.benchmark(args)
