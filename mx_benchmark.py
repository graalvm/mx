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
import time
import traceback
import uuid
from argparse import ArgumentParser
import os.path

import mx


_bm_suite_java_vms = {}
_bm_suites = {}
_benchmark_executor = None


class BenchmarkSuite(object):
    """
    A harness for a benchmark suite.

    A suite needs to be registered with mx_benchmarks.add_bm_suite.
    """
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

    def benchmarkList(self, bmSuiteArgs):
        """Returns the list of the benchmarks provided by this suite.

        :param list bmSuiteArgs: List of string arguments to the suite.
        :return: List of benchmark string names.
        :rtype: list
        """
        # TODO: Remove old-style benchmarks after updating downstream suites.
        return self.benchmarks()

    def benchmarks(self):
        # Deprecated, consider using `benchmarkList` instead!
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
            List of measurement result dictionaries, each corresponding to a datapoint.

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


def add_bm_suite(suite, mxsuite=None):
    if mxsuite is None:
        mxsuite = mx.currently_loading_suite.get()
    if suite.name() in _bm_suites:
        raise RuntimeError("Benchmark suite '{0}' already exists.".format(suite.name()))
    setattr(suite, ".mxsuite", mxsuite)
    _bm_suites[suite.name()] = suite


class Rule(object):
    # the maximum size of a string field
    max_string_field_length = 255

    @staticmethod
    def crop_front(prefix=""):
        """Returns a function that truncates a string at the start."""
        assert len(prefix) < Rule.max_string_field_length
        def _crop(path):
            if len(path) < Rule.max_string_field_length:
                return str(path)
            return str(prefix + path[-(Rule.max_string_field_length-len(prefix)):])
        return _crop

    @staticmethod
    def crop_back(suffix=""):
        """Returns a function that truncates a string at the end."""
        assert len(suffix) < Rule.max_string_field_length
        def _crop(path):
            if len(path) < Rule.max_string_field_length:
                return str(path)
            return str(path[:Rule.max_string_field_length-len(suffix)] + suffix)
        return _crop

    def parse(self, text):
        """Create a dictionary of variables for every measurment.

        :param text: The standard output of the benchmark.
        :type text: str
        :return: Iterable of dictionaries with the matched variables.
        :rtype: iterable
        """
        raise NotImplementedError()


class BaseRule(Rule):
    """A rule parses a raw result and a prepares a structured measurement using a replacement
    template.

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

    def __init__(self, replacement):
        self.replacement = replacement

    def parseResults(self, text):
        """Parses the raw result of a benchmark and create a dictionary of variables
        for every measurment.

        :param text: The standard output of the benchmark.
        :type text: str
        :return: Iterable of dictionaries with the matched variables.
        :rtype: iterable
        """
        raise NotImplementedError()

    def parse(self, text):
        datapoints = []
        capturepat = re.compile(r"<([a-zA-Z_][0-9a-zA-Z_]*)>")
        varpat = re.compile(r"\$([a-zA-Z_][0-9a-zA-Z_]*)")
        for iteration, m in enumerate(self.parseResults(text)):
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
                    v = capturepat.sub(lambda vm: m[vm.group(1)], v)
                    # Convert to a different type.
                    if vtype is str:
                        inst = str(v)
                    elif vtype is int:
                        inst = int(v)
                    elif vtype is float:
                        inst = float(v)
                    elif vtype is bool:
                        inst = bool(v)
                    elif hasattr(vtype, '__call__'):
                        inst = vtype(v)
                    else:
                        raise RuntimeError("Cannot handle type {0}".format(vtype))
                if type(inst) not in [str, int, float, bool]:
                    raise RuntimeError("Object has unknown type: {0}".format(inst))
                datapoint[key] = inst
            datapoints.append(datapoint)
        return datapoints


class StdOutRule(BaseRule):
    """Each rule contains a parsing pattern and a replacement template.

    A parsing pattern is a regex that may contain any number of named groups,
    as shown in the example:

        r"===== DaCapo (?P<benchmark>[a-z]+) PASSED in (?P<value>[0-9]+) msec ====="

    The above parsing regex captures the benchmark name into a variable `benchmark`
    and the elapsed number of milliseconds into a variable called `value`.
    """

    def __init__(self, pattern, replacement):
        super(StdOutRule, self).__init__(replacement)
        self.pattern = pattern

    def parseResults(self, text):
        return (m.groupdict() for m in re.finditer(self.pattern, text, re.MULTILINE))


class CSVBaseRule(BaseRule):
    """Parses a CSV file and creates a measurement result using the replacement."""

    def __init__(self, colnames, replacement, filter_fn=None, **kwargs):
        """
        :param colnames: list of column names of the CSV file. These names are used to
                         instantiate the replacement template.
        :type colnames: list
        :param filter_fn: function for filtering and transforming raw results
        :type filter_fn: function
        """
        super(CSVBaseRule, self).__init__(replacement)
        self.colnames = colnames
        self.kwargs = kwargs
        self.filter_fn = filter_fn if filter_fn else self.filterResult

    def filterResult(self, r):
        """Filters and transforms a raw result

        :return: Dictionary of variables or None if the result should be omitted.
        :rtype: dict or None
        """
        return r

    def getCSVFiles(self, text):
        """Get the CSV files which should be parsed.

        :param text: The standard output of the benchmark.
        :type text: str
        :return: List of file names
        :rtype: list
        """
        raise NotImplementedError()

    def parseResults(self, text):
        import csv
        l = []
        files = self.getCSVFiles(text)
        for filename in files:
            with open(filename, 'rb') as csvfile:
                csvReader = csv.DictReader(csvfile, fieldnames=self.colnames, **self.kwargs)
                l = l + [r for r in (self.filter_fn(x) for x in csvReader) if r]
        return l


class CSVFixedFileRule(CSVBaseRule):
    """CSV rule that parses a file with a predefined name."""

    def __init__(self, filename, *args, **kwargs):
        super(CSVFixedFileRule, self).__init__(*args, **kwargs)
        self.filename = filename

    def getCSVFiles(self, text):
        return [self.filename]


class CSVStdOutFileRule(CSVBaseRule):
    """CSV rule that looks for CSV file names in the output of the benchmark."""

    def __init__(self, pattern, match_name, *args, **kwargs):
        super(CSVStdOutFileRule, self).__init__(*args, **kwargs)
        self.pattern = pattern
        self.match_name = match_name

    def getCSVFiles(self, text):
        return (m.groupdict()[self.match_name] for m in re.finditer(self.pattern, text, re.MULTILINE))


class JMHJsonRule(Rule):
    """Parses a JSON file produced by JMH and creates a measurement result."""

    extra_jmh_keys = [
        "mode",
        "threads",
        "forks",
        "warmupIterations",
        "warmupTime",
        "warmupBatchSize",
        "measurementIterations",
        "measurementTime",
        "measurementBatchSize",
        ]

    def __init__(self, filename, suiteName):
        self.filename = filename
        self.suiteName = suiteName

    def shortenPackageName(self, benchmark):
        """
        Returns an abbreviated name for the benchmark.
        Example: com.example.benchmark.Bench -> c.e.b.Bench
        The full name is stored in the `extra.jmh.benchmark` property.
        """
        s = benchmark.split(".")
        # class and method
        clazz = s[-2:]
        package = [str(x[0]) for x in s[:-2]]
        return ".".join(package + clazz)

    def benchSuiteName(self):
        return self.suiteName

    def getExtraJmhKeys(self):
        return JMHJsonRule.extra_jmh_keys

    def parse(self, text):
        r = []
        with open(self.filename) as fp:
            for result in json.load(fp):

                benchmark = result["benchmark"]
                mode = result["mode"]

                pm = result["primaryMetric"]
                unit = pm["scoreUnit"]
                unit_parts = unit.split("/")

                if mode == "thrpt":
                    # Throughput, ops/time
                    metricName = "throughput"
                    better = "higher"
                    if len(unit_parts) == 2:
                        metricUnit = "op/" + unit_parts[1]
                    else:
                        metricUnit = unit
                elif mode in ["avgt", "sample", "ss"]:
                    # Average time, Sampling time, Single shot invocation time
                    metricName = "time"
                    better = "lower"
                    if len(unit_parts) == 2:
                        metricUnit = unit_parts[0]
                    else:
                        metricUnit = unit
                else:
                    raise RuntimeError("Unknown benchmark mode {0}".format(mode))


                d = {
                    "bench-suite" : self.benchSuiteName(),
                    "benchmark" : self.shortenPackageName(benchmark),
                    "metric.name": metricName,
                    "metric.unit": metricUnit,
                    "metric.score-function": "id",
                    "metric.better": better,
                    "metric.type": "numeric",
                    # full name
                    "extra.jmh.benchmark" : benchmark,
                }

                if "params" in result:
                    # add all parameter as a single string
                    d["extra.jmh.params"] = ", ".join(["=".join(kv) for kv in result["params"].iteritems()])
                    # and also the individual values
                    for k, v in result["params"].iteritems():
                        d["extra.jmh.param." + k] = str(v)

                for k in self.getExtraJmhKeys():
                    if k in result:
                        d["extra.jmh." + k] = str(result[k])

                for jmhFork, rawData in enumerate(pm["rawData"]):
                    for iteration, data in enumerate(rawData):
                        d2 = d.copy()
                        d2.update({
                          "metric.value": float(data),
                          "metric.iteration": int(iteration),
                          "extra.jmh.fork": str(jmhFork),
                        })
                        r.append(d2)
        return r


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
        runretval = self.runAndReturnStdOut(benchmarks, bmSuiteArgs)
        if len(runretval) == 3:
            retcode, out, dims = runretval
            return self.validateStdoutWithDimensions(
                out, benchmarks, bmSuiteArgs, retcode=retcode, dims=dims)
        else:
            # TODO: Remove old-style validateStdOut after updating downstream suites.
            retcode, out = runretval
            return self.validateStdout(out, benchmarks, bmSuiteArgs, retcode=retcode)

    # TODO: Remove once all the downstream suites become up-to-date.
    def validateStdout(self, out, benchmarks, bmSuiteArgs, retcode=None):
        return self.validateStdoutWithDimensions(
            out, benchmarks, bmSuiteArgs, retcode=retcode, dims={})

    def validateStdoutWithDimensions(
        self, out, benchmarks, bmSuiteArgs, retcode=None, dims=None, *args, **kwargs):
        """Validate out against the parse rules and create data points.

        The dimensions from the `dims` dict are added to each datapoint parsed from the
        standard output.

        Subclass may override to customize validation.
        """
        if dims is None:
            dims = {}

        def compiled(pat):
            if type(pat) is str:
                return re.compile(pat)
            return pat

        flaky = False
        for pat in self.flakySuccessPatterns():
            if compiled(pat).search(out):
                flaky = True
        if not flaky:
            if retcode:
                if not self.validateReturnCode(retcode):
                    raise RuntimeError(
                        "Benchmark failed, exit code: {0}".format(retcode))
            for pat in self.failurePatterns():
                if compiled(pat).search(out):
                    raise RuntimeError("Benchmark failed, failure pattern found. Benchmark(s): {0}".format(benchmarks))
            success = False
            for pat in self.successPatterns():
                if compiled(pat).search(out):
                    success = True
            if not success:
                raise RuntimeError("Benchmark failed, success pattern not found. Benchmark(s): {0}".format(benchmarks))

        datapoints = []
        for rule in self.rules(out, benchmarks, bmSuiteArgs):
            parsedpoints = rule.parse(out)
            for datapoint in parsedpoints:
                datapoint.update(dims)
            datapoints.extend(parsedpoints)
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

    This suite relies on the `--jvm-config` flag to specify which JVM must be used to
    run. The suite comes with methods `jvmConfig`, `vmArgs` and `runArgs` that know how
    to extract the `--jvm-config` and the VM-and-run arguments to the benchmark suite
    (see the `benchmark` method for more information).
    """
    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        """Creates a list of arguments for the JVM using the suite arguments.

        :param list benchmarks: List of benchmarks from the suite to execute.
        :param list bmSuiteArgs: Arguments passed to the suite.
        :return: A list of command-line arguments.
        :rtype: list
        """
        raise NotImplementedError()

    def workingDirectory(self, benchmarks, bmSuiteArgs):
        """Returns the desired working directory for running the benchmark.

        By default it returns `None`, meaning that the working directory is not be
        changed. It is meant to be overridden in subclasses when necessary.
        """
        return None

    def vmAndRunArgs(self, bmSuiteArgs):
        return splitArgs(bmSuiteArgs, "--")

    def splitJvmConfigArg(self, bmSuiteArgs):
        parser = ArgumentParser()
        parser.add_argument("--jvm", default=None,
            help="JVM to run the benchmark with, for example 'server' or 'client'.")
        parser.add_argument("--jvm-config", default=None,
            help="JVM configuration for the selected JVM, for example 'graal-core'.")
        args, remainder = parser.parse_known_args(self.vmAndRunArgs(bmSuiteArgs)[0])
        return args.jvm, args.jvm_config, remainder

    def jvm(self, bmSuiteArgs):
        """Returns the value of the `--jvm` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[0]

    def jvmConfig(self, bmSuiteArgs):
        """Returns the value of the `--jvm-config` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[1]

    def vmArgs(self, bmSuiteArgs):
        """Returns the VM arguments for the benchmark."""
        return self.splitJvmConfigArg(bmSuiteArgs)[2]

    def runArgs(self, bmSuiteArgs):
        """Returns the run arguments for the benchmark."""
        return self.vmAndRunArgs(bmSuiteArgs)[1]

    def getJavaVm(self, bmSuiteArgs):
        jvm = self.jvm(bmSuiteArgs)
        jvmConfig = self.jvmConfig(bmSuiteArgs)
        if jvm is None:
            if mx.get_opts().vm is not None:
                mx.log("Defaulting --jvm to the deprecated --vm value. Please use --jvm.")
                jvm = mx.get_opts().vm
            else:
                mx.log("Defaulting the JVM to 'server'.")
                jvm = "server"
        if jvmConfig is None:
            mx.log("Defaulting --jvm-config to 'default'. Consider adding --jvm-config.")
            jvmConfig = "default"
        return get_java_vm(jvm, jvmConfig)

    def before(self, bmSuiteArgs):
        self.getJavaVm(bmSuiteArgs).run(".", ["-version"])

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        jvm = self.getJavaVm(bmSuiteArgs)
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        args = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        if args is None:
            return 0, "", {}
        return jvm.run(cwd, args)


class JavaVm(object): #pylint: disable=R0922
    """Base class for objects that can run Java VMs."""

    def name(self):
        """Returns the unique name of the Java VM (e.g. server, client, or jvmci)."""
        raise NotImplementedError()

    def config_name(self):
        """Returns the config name for a VM (e.g. graal-core or graal-enterprise)."""
        raise NotImplementedError()

    def run(self, cwd, args):
        """Runs the JVM with the specified args.

        Returns an exit code, a capture of the standard output, and a dictionary of
        extra dimensions to incorporate into the datapoints.

        :param str cwd: Current working directory.
        :param list args: List of command-line arguments for the VM.
        :return: A tuple with an exit-code, stdout, and a dict with extra dimensions.
        :rtype: tuple
        """
        raise NotImplementedError()


class OutputCapturingJavaVm(JavaVm): #pylint: disable=R0921
    """A convenience class for running Java VMs."""

    def post_process_command_line_args(self, suiteArgs):
        """Adapts command-line arguments to run the specific JVMCI VM."""
        raise NotImplementedError()

    def dimensions(self, cwd, args, code, out):
        """Returns a list of additional dimensions to put into every datapoint."""
        raise NotImplementedError()

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        """Runs JVM with the specified arguments stdout and stderr, and working dir."""
        raise NotImplementedError()

    def run(self, cwd, args):
        out = mx.TeeOutputCapture(mx.OutputCapture())
        args = self.post_process_command_line_args(args)
        mx.log("Running JVM with args: {0}".format(args))
        code = self.run_java(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)
        out = out.underlying.data
        dims = self.dimensions(cwd, args, code, out)
        return code, out, dims


class DefaultJavaVm(OutputCapturingJavaVm):
    def __init__(self, raw_name, raw_config_name):
        self.raw_name = raw_name
        self.raw_config_name = raw_config_name

    def name(self):
        return self.raw_name

    def config_name(self):
        return self.raw_config_name

    def post_process_command_line_args(self, args):
        return args

    def dimensions(self, cwd, args, code, out):
        return {
            "host-vm": self.name(),
            "host-vm-config": self.config_name(),
        }

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        mx.get_jdk().run_java(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)


class DummyJavaVm(OutputCapturingJavaVm):
    """
    Dummy VM to work around: "pylint #111138 disabling R0921 does'nt work"
    https://www.logilab.org/ticket/111138

    Note that the warning R0921 (abstract-class-little-used) has been removed
    from pylint 1.4.3.
    """
    pass


def add_java_vm(javavm):
    key = (javavm.name(), javavm.config_name())
    if key in _bm_suite_java_vms:
        raise RuntimeError("Java VM and config '{0}' already exist.".format(key))
    _bm_suite_java_vms[key] = javavm


def get_java_vm(vm_name, jvmconfig):
    key = (vm_name, jvmconfig)
    if not key in _bm_suite_java_vms:
        raise RuntimeError("Java VM and config '{0}' do not exist.".format(key))
    return _bm_suite_java_vms[key]


class TestBenchmarkSuite(JavaBenchmarkSuite):
    """Example suite used for testing and as a subclassing template.
    """
    def name(self):
        return "test"

    def validateReturnCode(self, retcode):
        return True

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


class JMHBenchmarkSuiteBase(JavaBenchmarkSuite):
    """Base class for JMH based benchmark suites."""

    jmh_result_file = "jmh_result.json"

    def extraRunArgs(self):
        return ["-rff", JMHBenchmarkSuiteBase.jmh_result_file, "-rf", "json"]

    def extraVmArgs(self):
        return []

    def getJMHEntry(self):
        raise NotImplementedError()

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        if benchmarks is None:
            benchmarks = []
        vmArgs = self.vmArgs(bmSuiteArgs) + self.extraVmArgs()
        runArgs = self.extraRunArgs() + self.runArgs(bmSuiteArgs)
        return vmArgs + self.getJMHEntry() + ['--jvmArgsPrepend', ' '.join(vmArgs)] + runArgs + benchmarks

    def benchmarkList(self, bmSuiteArgs):
        benchmarks = None
        jvm = self.getJavaVm(bmSuiteArgs)
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        args = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        _, out, _ = jvm.run(cwd, args +  ["-l"])
        benchs = out.splitlines()
        assert benchs[0].startswith("Benchmarks:")
        return benchs[1:]

    def successPatterns(self):
        return [
            re.compile(
                r"# Run complete.",
                re.MULTILINE)
        ]

    def benchSuiteName(self):
        return self.name()

    def failurePatterns(self):
        return [re.compile(r"<failure>")]

    def flakySuccessPatterns(self):
        return []

    def rules(self, out, benchmarks, bmSuiteArgs):
        return [JMHJsonRule(JMHBenchmarkSuiteBase.jmh_result_file, self.benchSuiteName())]


class JMHRunnerBenchmarkSuite(JMHBenchmarkSuiteBase):
    """JMH benchmark suite that uses jmh-runner to execute projects with JMH benchmarks."""

    def extraVmArgs(self):
        # find all projects with a direct JMH dependency
        jmhProjects = []
        for p in mx.projects_opt_limit_to_suites():
            if 'JMH' in [x.name for x in p.deps]:
                jmhProjects.append(p)
        cp = mx.classpath([p.name for p in jmhProjects], jdk=mx.get_jdk())

        return ['-cp', cp]

    def getJMHEntry(self):
        return ["org.openjdk.jmh.Main"]



class JMHJarBenchmarkSuite(JMHBenchmarkSuiteBase):
    """
    JMH benchmark suite that executes microbenchmarks in a JMH jar.

    This suite relies on the `--jmh-jar` and `--jmh-name` to be set. The former
    specifies the path to the JMH jar files. The later is the name suffix that is use
    for the bench-suite property.
    """

    def benchSuiteName(self):
        return "jmh-" + self.jmhName()

    def vmArgs(self, bmSuiteArgs):
        vmArgs = super(JMHJarBenchmarkSuite, self).vmArgs(bmSuiteArgs)
        parser = ArgumentParser(add_help=False)
        parser.add_argument("--jmh-jar", default=None)
        parser.add_argument("--jmh-name", default=None)
        args, remaining = parser.parse_known_args(vmArgs)
        self.jmh_jar = args.jmh_jar
        self.jmh_name = args.jmh_name
        return remaining

    def getJMHEntry(self):
        return ["-jar", self.jmhJAR()]

    def jmhName(self):
        if self.jmh_name is None:
            mx.abort("Please use the --jmh-name benchmark suite argument to set the name of the JMH suite.")
        return self.jmh_name

    def jmhJAR(self):
        if self.jmh_jar is None:
            mx.abort("Please use the --jmh-jar benchmark suite argument to set the JMH jar file.")
        jmh_jar = os.path.expanduser(self.jmh_jar)
        if not os.path.exists(jmh_jar):
            mx.abort("The --jmh-jar argument points to a non-existing file: " + jmh_jar)
        return jmh_jar


class JMHRunnerMxBenchmarkSuite(JMHRunnerBenchmarkSuite):
    def name(self):
        return "jmh-mx"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"


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

    def machineCpuClock(self):
        return -1

    def machineCpuFamily(self):
        return "unknown"

    def machineRam(self):
        return -1

    def branch(self):
        mxsuite = mx.primary_suite()
        name = mxsuite.vc and mxsuite.vc.active_branch(mxsuite.dir, abortOnError=False) or "<unknown>"
        return name

    def buildUrl(self):
        return mx.get_env("BUILD_URL", default="")

    def buildNumber(self):
        build_num = mx.get_env("BUILD_NUMBER", default="")
        if not build_num:
            return -1
        return int(build_num)

    def checkEnvironmentVars(self):
        pass

    def dimensions(self, suite, mxBenchmarkArgs, bmSuiteArgs):
        standard = {
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
          "machine.cpu-clock": self.machineCpuClock(),
          "machine.cpu-family": self.machineCpuFamily(),
          "machine.ram": self.machineRam(),
          "branch": self.branch(),
          "build.url": self.buildUrl(),
          "build.number": self.buildNumber(),
        }

        def commit_info(prefix, mxsuite, include_ts=False):
            vc = mxsuite.vc
            if vc is None:
                return {}
            info = vc.parent_info(mxsuite.dir)
            return {
              prefix + "commit.rev": vc.parent(mxsuite.dir),
              prefix + "commit.repo-url": vc.default_pull(mxsuite.dir),
              prefix + "commit.author": info["author"],
              prefix + "commit.author-ts": info["author-ts"],
              prefix + "commit.committer": info["committer"],
              prefix + "commit.committer-ts": info["committer-ts"],
            }

        standard.update(commit_info("", mx.primary_suite(), include_ts=True))
        for (name, mxsuite) in mx._suites.iteritems():
            standard.update(commit_info("extra." + name + ".", mxsuite,
                include_ts=False))
        return standard

    def getSuiteAndBenchNames(self, args, bmSuiteArgs):
        argparts = args.benchmark.split(":")
        suitename = argparts[0]
        if len(argparts) == 2:
            benchspec = argparts[1]
        else:
            benchspec = ""
        suite = _bm_suites.get(suitename)
        if not suite:
            mx.abort("Cannot find benchmark suite '{0}'.  Available suites are {1}".format(suitename, _bm_suites.keys()))
        if benchspec is "*":
            return (suite, [[b] for b in suite.benchmarkList(bmSuiteArgs)])
        elif benchspec is "":
            return (suite, [None])
        elif not benchspec in suite.benchmarkList(bmSuiteArgs):
            mx.abort("Cannot find benchmark '{0}' in suite '{1}'.  Available benchmarks are {2}".format(
                benchspec, suitename, suite.benchmarkList(bmSuiteArgs)))
        else:
            return (suite, [[benchspec]])

    def execute(self, suite, benchnames, mxBenchmarkArgs, bmSuiteArgs):
        def postProcess(results):
            processed = []
            dim = self.dimensions(suite, mxBenchmarkArgs, bmSuiteArgs)
            for result in results:
                if not isinstance(result, dict):
                    result = result.__dict__
                point = dim.copy()
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
            "--results-file",
            default="bench-results.json",
            help="Path to JSON output file with benchmark results.")
        parser.add_argument(
            "--machine-name", default=None, help="Abstract name of the target machine.")
        mxBenchmarkArgs = parser.parse_args(mxBenchmarkArgs)

        self.checkEnvironmentVars()

        suite, benchNamesList = self.getSuiteAndBenchNames(mxBenchmarkArgs, bmSuiteArgs)

        results = []

        failures_seen = False
        suite.before(bmSuiteArgs)
        start_time = time.time()
        for benchnames in benchNamesList:
            suite.validateEnvironment()
            try:
                partialResults = self.execute(
                    suite, benchnames, mxBenchmarkArgs, bmSuiteArgs)
                results.extend(partialResults)
            except RuntimeError:
                failures_seen = True
                mx.log(traceback.format_exc())
        end_time = time.time()

        for result in results:
            result["extra.benchmarking.start-ts"] = int(start_time)
            result["extra.benchmarking.end-ts"] = int(end_time)

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


def init_benchmark_suites():
    """Called after mx initialization if mx is the primary suite."""
    add_java_vm(DefaultJavaVm("server", "default"))
    add_bm_suite(JMHRunnerMxBenchmarkSuite())


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
        idx = args.index(separator)
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
