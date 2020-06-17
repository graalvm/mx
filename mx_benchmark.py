#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2016, Oracle and/or its affiliates. All rights reserved.
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

from __future__ import print_function

import json
import os.path
import platform
import re
import socket
import time
import traceback
import uuid
from argparse import ArgumentParser
from argparse import RawTextHelpFormatter
from argparse import SUPPRESS
from collections import OrderedDict

import mx

_bm_suites = {}
_benchmark_executor = None


# Contains an argument parser and its description.
class ParserEntry(object):
    def __init__(self, parser, description):
        """
        :param ArgumentParser parser: the parser
        :param str description: the description
        """
        self.parser = parser
        self.description = description


# Parsers used by different `mx benchmark` commands.
parsers = {}
_mx_benchmark_usage_example = "mx benchmark <suite>:<bench>"


def add_parser(name, parser_entry):
    """Add a named parser to be used in benchmark suites.
    :param str name: the name of the parser
    :param ParserEntry parser_entry: the parser and description
    :return:
    """
    if name in parsers:
        mx.abort("There is already a parser called '{}'".format(name))
    parsers[name] = parser_entry


def get_parser(name):
    """Gets the named parser
    :param str name: the name of the parser
    :rtype: ArgumentParser
    """
    return parsers[name].parser

class VmRegistry(object):
    def __init__(self, vm_type_name, short_vm_type_name=None, default_vm=None, known_host_registries=None):
        """

        :param str vm_type_name: full VM type name (e.g., "Java")
        :param str short_vm_type_name:
        :param default_vm: a callable which, given a config name gives a default VM name
        :param list[VmRegistry] known_host_registries: a list of known host VM registries
        """
        self.vm_type_name = vm_type_name + " VM"
        self.short_vm_type_name = short_vm_type_name if short_vm_type_name else vm_type_name.lower() + "-vm"
        assert default_vm is None or callable(default_vm)
        self.default_vm = default_vm
        assert re.compile(r"\A[a-z-]+\Z").match(self.short_vm_type_name)
        self._vms = OrderedDict()
        self._vms_suite = {}
        self._vms_priority = {}
        self._known_host_registries = known_host_registries or []
        add_parser(self.get_parser_name(), ParserEntry(
            ArgumentParser(add_help=False, usage=_mx_benchmark_usage_example + " -- <options> -- ..."),
            "\n\n{} selection flags, specified in the benchmark suite arguments:\n".format(self.vm_type_name)
        ))
        get_parser(self.get_parser_name()).add_argument("--{}".format(self.short_vm_type_name), default=None, help="{vm} to run the benchmark with.".format(vm=self.vm_type_name))
        get_parser(self.get_parser_name()).add_argument("--{}-config".format(self.short_vm_type_name), default=None, help="{vm} configuration for the selected {vm}.".format(vm=self.vm_type_name))
        # Separator to stack guest and host VM options. Though ignored, must be consumed by the parser.
        get_parser(self.get_parser_name()).add_argument('--guest', action='store_true', dest=SUPPRESS, default=None, help='Separator for --{vm}=host --guest --{vm}=guest VM configurations.'.format(vm=self.short_vm_type_name))

    def get_parser_name(self):
        return self.vm_type_name + "_parser"

    def get_known_guest_registries(self):
        return self._known_host_registries

    def get_default_vm(self, config):
        if self.default_vm:
            return self.default_vm(config, self._vms)
        return None

    def get_available_vm_configs_help(self):
        avail = ['--{}={} --{}-config={}'.format(self.short_vm_type_name, vm.name(), self.short_vm_type_name, vm.config_name()) for vm in self._vms.values()]
        return 'The following {} configurations are available:\n  {}'.format(self.vm_type_name, '\n  '.join(avail))

    def get_vm_from_suite_args(self, bmSuiteArgs, hosted=False, quiet=False, host_vm_only_as_default=False):
        """
        Helper function for suites or other VMs that need to create a JavaVm based on mx benchmark arguments.

        Suites that might need this should add `java_vm_parser_name` to their `parserNames`.

        :param list[str] bmSuiteArgs: the suite args provided by mx benchmark
        :param boolean host_vm_only_as_default:
                if true and `bmSuiteArgs` does not specify a VM, picks a host VM as default, discarding guest VMs.
        :return: a Vm as configured by the `bmSuiteArgs`.
        :rtype: Vm
        """
        vm_config_args = splitArgs(bmSuiteArgs, '--')[0]

        # Use --guest as separator to stack guest VMs (also within the same registry) e.g. --jvm=host_vm --guest --jvm=guest_vm.
        rest, args = rsplitArgs(vm_config_args, '--guest')
        check_guest_vm = '--guest' in vm_config_args

        args, unparsed_args = get_parser(self.get_parser_name()).parse_known_args(args)
        bmSuiteArgsPending = rest + unparsed_args

        arg_vm_type_name = self.short_vm_type_name.replace('-', '_')
        vm = getattr(args, arg_vm_type_name)
        vm_config = getattr(args, arg_vm_type_name + '_config')
        if vm is None:
            vm = self.get_default_vm(vm_config)
            if vm is None:
                vms = [(vm,
                         self._vms_suite[(vm, config)] == mx.primary_suite(),
                         ('hosted' in config) == hosted,
                         self._vms_priority[(vm, config)]
                         ) for (vm, config), vm_obj in self._vms.items() if (vm_config is None or config == vm_config) and not (host_vm_only_as_default and isinstance(vm_obj, GuestVm))]
                if not vms:
                    mx.abort("Could not find a {} to default to.\n{avail}".format(self.vm_type_name, avail=self.get_available_vm_configs_help()))
                vms.sort(key=lambda t: t[1:], reverse=True)
                vm = vms[0][0]
                if len(vms) == 1:
                    notice = mx.log
                    choice = vm
                else:
                    notice = mx.warn
                    seen = set()
                    choice = ' [' + '|'.join((c[0] for c in vms if c[0] not in seen and (seen.add(c[0]) or True))) + ']'
                if not quiet:
                    notice("Defaulting the {} to '{}'. Consider using --{} {}".format(self.vm_type_name, vm, self.short_vm_type_name, choice))
        if vm_config is None:
            vm_configs = [(config,
                            self._vms_suite[(vm, config)] == mx.primary_suite(),
                            ('hosted' in config) == hosted,
                            self._vms_priority[(vm, config)]
                            ) for (j, config) in self._vms if j == vm]
            if not vm_configs:
                mx.abort("Could not find a {vm_type} config to default to for {vm_type} '{vm}'.\n{avail}".format(vm=vm, vm_type=self.vm_type_name, avail=self.get_available_vm_configs_help()))
            vm_configs.sort(key=lambda t: t[1:], reverse=True)
            vm_config = vm_configs[0][0]
            if len(vm_configs) == 1:
                notice = mx.log
                choice = vm_config
            else:
                notice = mx.warn
                seen = set()
                choice = ' [' + '|'.join((c[0] for c in vm_configs if c[0] not in seen and (seen.add(c[0]) or True))) + ']'
            if not quiet:
                notice("Defaulting the {} config to '{}'. Consider using --{}-config {}.".format(self.vm_type_name, vm_config, self.short_vm_type_name, choice))
        vm_object = self.get_vm(vm, vm_config)

        if check_guest_vm and not isinstance(vm_object, GuestVm):
            mx.abort("{vm_type} '{vm}' with config '{vm_config}' is declared as --guest but it's NOT a guest VM.".format(vm=vm, vm_type=self.vm_type_name, vm_config=vm_config))

        if isinstance(vm_object, GuestVm):
            host_vm = vm_object.hosting_registry().get_vm_from_suite_args(bmSuiteArgsPending, hosted=True, quiet=quiet, host_vm_only_as_default=True)
            vm_object = vm_object.with_host_vm(host_vm)
        return vm_object

    def add_vm(self, vm, suite=None, priority=0):
        key = (vm.name(), vm.config_name())
        if key in self._vms:
            mx.abort("{} and config '{}' already exist.".format(self.vm_type_name, key))
        self._vms[key] = vm
        self._vms_suite[key] = suite
        self._vms_priority[key] = priority

    def get_vm(self, vm_name, vm_config):
        key = (vm_name, vm_config)
        if key not in self._vms:
            mx.abort("{} and config '{}' do not exist.\n{}".format(self.vm_type_name, key, self.get_available_vm_configs_help()))
        return self._vms[key]

    def get_vms(self):
        return list(self._vms.values())

# JMH suite parsers.
add_parser("jmh_jar_benchmark_suite_vm", ParserEntry(
    ArgumentParser(add_help=False, usage=_mx_benchmark_usage_example + " -- <options> -- ..."),
    "\n\nVM selection flags for JMH benchmark suites:\n"
))
get_parser("jmh_jar_benchmark_suite_vm").add_argument("--jmh-jar", default=None)
get_parser("jmh_jar_benchmark_suite_vm").add_argument("--jmh-name", default=None)
get_parser("jmh_jar_benchmark_suite_vm").add_argument("--jmh-benchmarks", default=None)


class BenchmarkSuite(object):
    """
    A harness for a benchmark suite.

    A suite needs to be registered with mx_benchmarks.add_bm_suite.
    """
    def __init__(self, *args, **kwargs):
        super(BenchmarkSuite, self).__init__(*args, **kwargs)
        self._desired_version = None
        self._suite_dimensions = {}

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

        :param list[str] bmSuiteArgs: List of string arguments to the suite.
        :return: List of benchmark string names.
        :rtype: list[str]
        """
        # TODO: raise NotImplementedError() here
        mx.log_deprecation("'benchmarks' method is deprecated ! Use 'benchmarkList' instead.")
        return self.benchmarks()

    def benchmarks(self):
        # Deprecated, consider using `benchmarkList` instead!
        raise NotImplementedError()

    def desiredVersion(self):
        """Returns the benchmark suite version that is requested for execution.

        :return: suite version.
        :rtype: str
        """
        return self._desired_version

    def setDesiredVersion(self, version):
        self._desired_version = version

    def validateEnvironment(self):
        """Validates the environment and raises exceptions if validation fails.

        Can be overridden to check for existence of required environment variables
        before the benchmark suite executed.
        """

    def vmArgs(self, bmSuiteArgs):
        """Extracts the VM flags from the list of arguments passed to the suite.

        :param list[str] bmSuiteArgs: List of string arguments to the suite.
        :return: A list of string flags that are VM flags.
        :rtype: list[str]
        """
        raise NotImplementedError()

    def runArgs(self, bmSuiteArgs):
        """Extracts the run flags from the list of arguments passed to the suite.

        :param list[str] bmSuiteArgs: List of string arguments to the suite.
        :return: A list of string flags that are arguments for the suite.
        :rtype: list[str]
        """
        raise NotImplementedError()

    def before(self, bmSuiteArgs):
        """Called exactly once before any benchmark invocations begin.

        Useful for outputting information such as platform version, OS, etc.

        Arguments: see `run`.
        """

    def after(self, bmSuiteArgs):
        """Called exactly once after all benchmark invocations are done.

        Useful for cleaning up after the benchmarks.

        Arguments: see `run`.
        """

    def parserNames(self):
        """Returns the list of parser names that this benchmark suite uses.

        This is used to more accurately show command line options tied to a specific
        benchmark suite.
        :rtype: list[str]
        """
        return []

    def suiteDimensions(self):
        """Returns context specific dimensions that will be integrated in the measurement
        data.

        :rtype: dict
        """
        return self._suite_dimensions

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

    def workingDirectory(self, benchmarks, bmSuiteArgs):
        """Returns the desired working directory for running the benchmark.

        By default it returns `None`, meaning that the working directory is not be
        changed. It is meant to be overridden in subclasses when necessary.
        """
        return None


def add_bm_suite(suite, mxsuite=None):
    if mxsuite is None:
        mxsuite = mx.currently_loading_suite.get()

    full_name = "{}-{}".format(suite.name(), suite.subgroup())
    if full_name in _bm_suites:
        raise RuntimeError("Benchmark suite full name '{0}' already exists.".format(full_name))
    _bm_suites[full_name] = suite
    setattr(suite, ".mxsuite", mxsuite)

    simple_name = suite.name()
    # If possible also register suite with simple_name
    if simple_name in _bm_suites:
        if _bm_suites[simple_name]:
            mx.log("Warning: Benchmark suite '{0}' name collision. Suites only available as '{0}-<subgroup>'.".format(simple_name))
        _bm_suites[simple_name] = None
    else:
        _bm_suites[simple_name] = suite


def bm_suite_valid_keys():
    return sorted([k for k, v in _bm_suites.items() if v])

def vm_registries():
    res = set()
    for bm_suite in _bm_suites.values():
        if isinstance(bm_suite, VmBenchmarkSuite):
            res.add(bm_suite.get_vm_registry())
    return res

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

    def _prepend_working_dir(self, filename):
        """Prepends the current working directory to the filename.
        Can only be called from within `parse()`.
        """
        if hasattr(self, "_cwd") and self._cwd and not os.path.isabs(filename):
            return os.path.join(self._cwd, filename)
        return filename


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
            for key, value in self.replacement.items():
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
                        if isinstance(v, str) and ',' in v and '.' not in v:
                            # accommodate different locale in float formatting
                            v = v.replace(',', '.')
                        inst = float(v)
                    elif vtype is bool:
                        inst = bool(v)
                    elif hasattr(vtype, '__call__'):
                        inst = vtype(v)
                    else:
                        raise RuntimeError("Cannot handle object '{0}' of expected type {1}".format(v, vtype))
                if not isinstance(inst, (str, int, float, bool)):
                    if type(inst).__name__ != 'long': # Python2: int(x) can result in a long
                        raise RuntimeError("Object '{}' has unknown type: {}".format(inst, type(inst)))
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
            with open(self._prepend_working_dir(filename), 'r') as csvfile:
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

    def getBenchmarkNameFromResult(self, result):
        return result["benchmark"]

    def parse(self, text):
        r = []
        with open(self._prepend_working_dir(self.filename)) as fp:
            for result in json.load(fp):

                benchmark = self.getBenchmarkNameFromResult(result)
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
                else:
                    # Average time, Sampling time, Single shot invocation time
                    better = "lower"
                    if len(unit_parts) == 2:
                        metricUnit = unit_parts[0]
                    else:
                        metricUnit = unit
                    if mode == "avgt":
                        metricName = "average-time"
                    elif mode == "sample":
                        metricName = "sample-time"
                    elif mode == "ss":
                        metricName = "single-shot"
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
                    d["extra.jmh.params"] = ", ".join(["=".join(kv) for kv in result["params"].items()])
                    # and also the individual values
                    for k, v in result["params"].items():
                        d["extra.jmh.param." + k] = str(v)

                for k in self.getExtraJmhKeys():
                    if k in result:
                        d["extra.jmh." + k] = str(result[k])

                if 'rawData' not in pm:
                    # we don't have the raw results, e.g. for the `sample` mode
                    # upload only the overall score
                    d.update({
                        "metric.value": float(pm['score']),
                    })
                    r.append(d)
                else:
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


class BenchmarkFailureError(RuntimeError):
    """Thrown when a benchmark execution results in an error."""

    def __init__(self, message, partialResults):
        super(BenchmarkFailureError, self).__init__(message)
        self.partialResults = partialResults


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
            mx.log_deprecation("'runAndReturnStdOut' must return exactly three elements !")
            retcode, out = runretval
            return self.validateStdout(out, benchmarks, bmSuiteArgs, retcode=retcode)

    # TODO: Remove once all the downstream suites become up-to-date.
    def validateStdout(self, out, benchmarks, bmSuiteArgs, retcode=None):
        mx.log_deprecation("'validateStdout' is deprecated ! Use 'validateStdoutWithDimensions' instead.'")
        return self.validateStdoutWithDimensions(
            out, benchmarks, bmSuiteArgs, retcode=retcode, dims={})

    def repairDatapoints(self, benchmarks, bmSuiteArgs, partialResults):
        """Repairs output results after a benchmark fails.

        Subclasses should override this method when they need to add failed datapoints.

        This method is called when the benchmark suite invocation completes abnormally,
        due to a non-zero exit code, a failure pattern in the standard output, or a
        missing success pattern. The benchmark suite must go through the partial list of
        datapoints, and add missing datapoints to it if necessary.

        The `error` field of each datapoint should not be modified in this benchmark,
        as it will be overwritten with the appropriate error message.
        """

    def repairDatapointsAndFail(self, benchmarks, bmSuiteArgs, partialResults, message):
        self.repairDatapoints(benchmarks, bmSuiteArgs, partialResults)
        for result in partialResults:
            result["error"] = message
        raise BenchmarkFailureError(message, partialResults)

    def validateStdoutWithDimensions(
        self, out, benchmarks, bmSuiteArgs, retcode=None, dims=None, extraRules=None):
        """Validate out against the parse rules and create data points.

        The dimensions from the `dims` dict are added to each datapoint parsed from the
        standard output.

        Subclass may override to customize validation.
        """
        if dims is None:
            dims = {}
        if extraRules is None:
            extraRules = []

        def compiled(pat):
            if isinstance(pat, str):
                return re.compile(pat)
            return pat

        flaky_skip = False
        for pat in self.flakySkipPatterns(benchmarks, bmSuiteArgs):
            if compiled(pat).search(out):
                flaky_skip = True
        if flaky_skip:
            mx.warn("Benchmark skipped, flaky pattern found. Benchmark(s): {0}".format(benchmarks))
            return []

        datapoints = []
        rules = self.rules(out, benchmarks, bmSuiteArgs) + extraRules

        for rule in rules:
            # pass working directory to rule without changing the signature of parse
            rule._cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
            parsedpoints = rule.parse(out)
            for datapoint in parsedpoints:
                datapoint.update(dims)
            datapoints.extend(parsedpoints)

        flaky = False
        for pat in self.flakySuccessPatterns():
            if compiled(pat).search(out):
                flaky = True
        if not flaky:
            if retcode is not None:
                if not self.validateReturnCode(retcode):
                    self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                        "Benchmark failed, exit code: {0}".format(retcode))
            for pat in self.failurePatterns():
                if compiled(pat).search(out):
                    self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                        "Benchmark failed, failure pattern found. Benchmark(s): {0}".format(benchmarks))
            success = False
            for pat in self.successPatterns():
                if compiled(pat).search(out):
                    success = True
            if len(self.successPatterns()) == 0:
                success = True
            if not success:
                self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                    "Benchmark failed, success pattern not found. Benchmark(s): {0}".format(benchmarks))

        return datapoints

    def validateReturnCode(self, retcode):
        return retcode == 0

    def flakySuccessPatterns(self):
        """List of regex pattern that can override matched failure and success patterns.

        If any of the patterns in this list match, the output will not be checked for
        failure or success patterns. The result will still be checked according to the
        `self.rules()`.
        If none of the patterns in this list match, the output is checked normally.

        This method should be overridden for suites that are known to be flaky.
        """
        return []

    def flakySkipPatterns(self, benchmarks, bmSuiteArgs):
        """List of regex pattern that indicate whether a benchmark run was flaky and
        the results should be ignored.

        If none of the patterns in this list match, the output is checked normally.

        The difference to `flakySuccessPatterns` is that the run will be ignored completely.
        No results will be produced.

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


class DeprecatedMixin(object):
    """ Mixin to deprecate benchmark suites. """
    def benchmarkList(self, bmSuiteArgs):
        try:
            return super(DeprecatedMixin, self).benchmarkList(bmSuiteArgs)
        except:
            return ["THIS SUITE IS DEPRECATED"]

    def alternative_suite(self):
        return None

    def warning_only(self):
        return False

    def run(self, *args, **kwargs):
        alternative_suite = self.alternative_suite()
        msg = "The `{0}` benchmark suite is deprecated! {1}".format(
              self.name(),
              "Consider using `{0}` instead.".format(alternative_suite)
              if alternative_suite else
              "(No alternatives provided.)"
        )
        if self.warning_only():
            mx.warn(msg)
        else:
            mx.abort(msg)
        return super(DeprecatedMixin, self).run(*args, **kwargs)


class AveragingBenchmarkMixin(object):
    """Provides utilities for computing the average time of the latest warmup runs.

    Note that this mixin expects that the main benchmark class produces a sequence of
    datapoints that have the metric.name dimension set to "warmup".
    To add the average, this mixin appends a new datapoint whose metric.name dimension
    is set to "time" by default.

    Benchmarks that mix in this class must manually invoke methods for computing extra
    iteration counts and averaging, usually in their run method.
    """

    def getExtraIterationCount(self, iterations):
        """
        Uses the number of warmup iterations to calculate the number of extra iterations
        needed by the benchmark to compute a more stable average result.
        Currently, this is 40% of the number of warmup iterations, at least 6 and at most 20.
        """
        return min(20, iterations, max(6, int(iterations * 0.4)))

    def addAverageAcrossLatestResults(self, results, metricName="time"):
        """
        Postprocess results to compute the resulting time by taking the average of last N runs,
        where N is obtained using getExtraIterationCount.
        """
        benchmarkNames = {r["benchmark"] for r in results}
        for benchmark in benchmarkNames:
            warmupResults = [result for result in results if result["metric.name"] == "warmup" and result["benchmark"] == benchmark]
            if warmupResults:
                lastIteration = max((result["metric.iteration"] for result in warmupResults))
                resultIterations = self.getExtraIterationCount(lastIteration + 1)

                warmupResultsToAverage = [result for result in warmupResults if result["metric.iteration"] >= lastIteration - resultIterations + 1]

                if len({result["metric.iteration"] for result in warmupResults}) != len(warmupResults):
                    mx.warn("Inconsistent number of iterations ! Duplicate iteration number found.")
                    mx.warn("Iteration results : {}".format(warmupResults))

                if len(warmupResultsToAverage) != resultIterations:
                    mx.warn("Inconsistent number of iterations !")
                    mx.warn("Expecting {} iterations, but got {} instead.".format(len(warmupResultsToAverage), resultIterations))
                    mx.warn("Iteration results : {}".format(warmupResults))

                scoresToAverage = [result["metric.value"] for result in warmupResultsToAverage]

                averageResult = min(warmupResults, key=lambda result: result["metric.iteration"]).copy()
                averageResult["metric.value"] = sum(scoresToAverage) / len(scoresToAverage)
                averageResult["metric.name"] = metricName
                averageResult["metric.average-over"] = resultIterations
                results.append(averageResult)


class WarnDeprecatedMixin(DeprecatedMixin):
    def warning_only(self):
        return True


class VmBenchmarkSuite(StdOutBenchmarkSuite):
    def vmArgs(self, bmSuiteArgs):
        args = self.vmAndRunArgs(bmSuiteArgs)[0]
        for parser_name in self.parserNames():
            parser = get_parser(parser_name)
            _, args = parser.parse_known_args(args)
        return args

    def parserNames(self):
        names = []

        def _acc(reg):
            names.append(reg.get_parser_name())
            for guest_reg in reg.get_known_guest_registries():
                _acc(guest_reg)
        _acc(self.get_vm_registry())
        return super(VmBenchmarkSuite, self).parserNames() + names

    def vmAndRunArgs(self, bmSuiteArgs):
        return splitArgs(bmSuiteArgs, "--")

    def runArgs(self, bmSuiteArgs):
        return self.vmAndRunArgs(bmSuiteArgs)[1]

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        return self.createVmCommandLineArgs(benchmarks, self.runArgs(bmSuiteArgs))

    def createVmCommandLineArgs(self, benchmarks, runArgs):
        """" Creates the arguments that need to be passed to the VM to run the benchmarks.
        :rtype: list
        """
        raise NotImplementedError()

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs) or '.'
        command = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        if command is None:
            return 0, "", {}
        vm = self.get_vm_registry().get_vm_from_suite_args(bmSuiteArgs)
        t = vm.run(cwd, command)
        if len(t) == 2:
            ret_code, out = t
            vm_dims = {}
        else:
            ret_code, out, vm_dims = t
        host_vm = None
        if isinstance(vm, GuestVm):
            host_vm = vm.host_vm()
            assert host_vm
        dims = {
            "vm": vm.name(),
            "host-vm": host_vm.name() if host_vm else vm.name(),
            "host-vm-config": self.host_vm_config_name(host_vm, vm),
            "guest-vm": vm.name() if host_vm else "none",
            "guest-vm-config": self.guest_vm_config_name(host_vm, vm),
        }
        for key, value in vm_dims.items():
            if key in dims and value != dims[key]:
                if value == 'none':
                    mx.warn("VM {}:{} ({}) tried overwriting {}='{original}' with '{}', keeping '{original}'".format(vm.name(), vm.config_name(), vm.__class__.__name__, key, value, original=dims[key]))
                    continue
                mx.warn("VM {}:{} ({}) is overwriting {}='{}' with '{}'".format(vm.name(), vm.config_name(), vm.__class__.__name__, key, dims[key], value))
            dims[key] = value
        return ret_code, out, dims

    def host_vm_config_name(self, host_vm, vm):
        return host_vm.config_name() if host_vm else vm.config_name()

    def guest_vm_config_name(self, host_vm, vm):
        return vm.config_name() if host_vm else "default"

    def validateStdoutWithDimensions(
        self, out, benchmarks, bmSuiteArgs, retcode=None, dims=None, extraRules=None):

        if extraRules is None:
            extraRules = []

        vm = self.get_vm_registry().get_vm_from_suite_args(bmSuiteArgs, quiet=True)
        extraRules += vm.rules(out, benchmarks, bmSuiteArgs)

        return super(VmBenchmarkSuite, self).validateStdoutWithDimensions(out=out, benchmarks=benchmarks, bmSuiteArgs=bmSuiteArgs, retcode=retcode, dims=dims, extraRules=extraRules)

    def get_vm_registry(self):
        """" Gets the VM registry used to run this type of benchmarks.
        :rtype: VmRegistry
        """
        raise NotImplementedError()


class JavaBenchmarkSuite(VmBenchmarkSuite): #pylint: disable=R0922
    """Convenience suite used for benchmarks running on the JDK.

    This suite relies on the `--jvm-config` flag to specify which JVM must be used to
    run. The suite comes with methods `jvmConfig`, `vmArgs` and `runArgs` that know how
    to extract the `--jvm-config` and the VM-and-run arguments to the benchmark suite
    (see the `benchmark` method for more information).
    """

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        """Creates a list of arguments for the JVM using the suite arguments.

        :param list[str] benchmarks: List of benchmarks from the suite to execute.
        :param list[str] bmSuiteArgs: Arguments passed to the suite.
        :return: A list of command-line arguments.
        :rtype: list[str]
        """
        raise NotImplementedError()

    def get_vm_registry(self):
        return java_vm_registry

    def splitJvmConfigArg(self, bmSuiteArgs):
        parser = get_parser(java_vm_registry.get_parser_name())
        args, remainder = parser.parse_known_args(self.vmAndRunArgs(bmSuiteArgs)[0])
        return args.jvm, args.jvm_config, remainder

    def jvm(self, bmSuiteArgs):
        """Returns the value of the `--jvm` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[0]

    def jvmConfig(self, bmSuiteArgs):
        """Returns the value of the `--jvm-config` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[1]

    def getJavaVm(self, bmSuiteArgs):
        return java_vm_registry.get_vm_from_suite_args(bmSuiteArgs)


class Vm(object): #pylint: disable=R0922
    """Base class for objects that can run Java VMs."""

    def name(self):
        """Returns the unique name of the Java VM (e.g. server, client, or jvmci)."""
        raise NotImplementedError()

    def config_name(self):
        """Returns the config name for a VM (e.g. graal-core or graal-enterprise)."""
        raise NotImplementedError()

    def rules(self, output, benchmarks, bmSuiteArgs):
        """Returns a list of rules required to parse the standard output.

        :param string output: Contents of the standard output.
        :param list benchmarks: List of benchmarks that were run.
        :param list bmSuiteArgs: Arguments to the benchmark suite (after first `--`).
        :return: List of StdOutRule parse rules.
        :rtype: list
        """
        return []

    def run(self, cwd, args):
        """Runs the JVM with the specified args.

        Returns an exit code, a capture of the standard output, and a dictionary of
        extra dimensions to incorporate into the datapoints.

        :param str cwd: Current working directory.
        :param list[str] args: List of command-line arguments for the VM.
        :return: A tuple with an exit-code, stdout, and a dict with extra dimensions.
        :rtype: tuple
        """
        raise NotImplementedError()


class GuestVm(Vm): #pylint: disable=R0921
    def __init__(self, host_vm=None):
        self._host_vm = host_vm

    def hosting_registry(self):
        """Returns the Host VM registry.
        :rtype: VmRegistry
        """
        raise NotImplementedError()

    def with_host_vm(self, host_vm):
        """Returns a copy of this VM with the host VM set to `host_vm`.
        :param Vm host_vm: the host VM to set in the returned object.
        :rtype: GuestVm
        """
        return self.__class__(host_vm)

    def host_vm(self):
        """Returns the Host VM.

        :rtype: Vm
        """
        return self._host_vm


class JavaVm(Vm):
    pass


def _get_default_java_vm(jvm_config, vms):
    if mx.get_opts().vm is not None and (jvm_config is None or (mx.get_opts().vm, jvm_config) in vms):
        mx.warn("Defaulting --jvm to the deprecated --vm value. Please use --jvm.")
        return mx.get_opts().vm
    return None


java_vm_registry = VmRegistry("Java", "jvm", _get_default_java_vm)
js_vm_registry = VmRegistry("JavaScript", "js", known_host_registries=[java_vm_registry])


def _get_vm_options_for_config_extraction(run_args):
    vm_opts = []
    if run_args:
        for arg in run_args:
            for opt in arg.split(" "):
                if opt.startswith("-Xm"):
                    vm_opts.append(opt)
                if (opt.startswith("-XX:+Use") or opt.startswith("-XX:-Use")) and opt.endswith("GC"):
                    vm_opts.append(opt)
    vm_opts.append("-XX:+PrintCommandLineFlags")
    return vm_opts


def _get_gc_info(version_out):
    gc = ""
    initial_heap_size = -1
    max_heap_size = -1

    for line in version_out.splitlines():
        if "-XX:+PrintCommandLineFlags" in line:
            for flag in line.split():
                if flag.startswith("-XX:+Use") and flag.endswith("GC"):
                    gc = flag[8:]
                if flag.startswith("-XX:InitialHeapSize="):
                    initial_heap_size = int(flag.split("=")[1])
                if flag.startswith("-XX:MaxHeapSize="):
                    max_heap_size = int(flag.split("=")[1])
    mx.logv("Detected GC is '{}'. Heap size : Initial = {}, Max = {}".format(gc, initial_heap_size, max_heap_size))
    return gc, initial_heap_size, max_heap_size


class OutputCapturingVm(Vm): #pylint: disable=R0921
    """A convenience class for running Non-Java VMs."""

    def post_process_command_line_args(self, suiteArgs):
        """Adapts command-line arguments to run the specific VM configuration."""
        raise NotImplementedError()

    def dimensions(self, cwd, args, code, out):
        """Returns a dict of additional dimensions to put into every datapoint.
        :rtype: dict
        """
        return {}

    def extract_vm_info(self, args=None):
        """Extract vm information."""
        pass

    def run_vm(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        """Runs JVM with the specified arguments stdout and stderr, and working dir."""
        raise NotImplementedError()

    def run(self, cwd, args):
        self.extract_vm_info(args)
        out = mx.TeeOutputCapture(mx.OutputCapture())
        args = self.post_process_command_line_args(args)
        mx.log("Running {0} with args: {1}".format(self.name(), args))
        code = self.run_vm(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)
        out = out.underlying.data
        dims = self.dimensions(cwd, args, code, out)
        return code, out, dims


class OutputCapturingJavaVm(OutputCapturingVm): #pylint: disable=R0921
    """A convenience class for running Java VMs."""

    def __init__(self):
        super(OutputCapturingJavaVm, self).__init__()
        self._vm_info = None

    def extract_vm_info(self, args=None):
        if args is None:
            # This method will force the caller to pass 'args' in the future to ensure correctness of the output
            mx.log_deprecation("Downstream suite must pass the VM arguments to ensure valid VM info extraction !")
            args = []
        args = self.post_process_command_line_args(args)
        if self._vm_info is None:
            self._vm_info = {}
            with mx.DisableJavaDebugging():
                java_version_out = mx.TeeOutputCapture(mx.OutputCapture())
                vm_opts = _get_vm_options_for_config_extraction(args)
                vm_args = vm_opts + ["-version"]
                mx.logv("Extracting vm info by calling : java {}".format(' '.join(vm_args)))
                code = self.run_java(vm_args, out=java_version_out, err=java_version_out, cwd=".")
                if code == 0:
                    command_output = java_version_out.underlying.data
                    gc, initial_heap, max_heap = _get_gc_info(command_output)
                    self._vm_info["platform.gc"] = gc
                    self._vm_info["platform.initial-heap-size"] = initial_heap
                    self._vm_info["platform.max-heap-size"] = max_heap

                    version_output = command_output.splitlines()
                    assert len(version_output) >= 3
                    if len(version_output) > 3:
                        # removing the output of PrintCommandLineFlags from above
                        # and any other warnings or info like "Picked up : <ENV VAR>"
                        version_output = version_output[-3:]
                    assert "version" in version_output[0]
                    jdk_version_number = version_output[0].split("\"")[1]
                    version = mx.VersionSpec(jdk_version_number)
                    jdk_major_version = version.parts[1] if version.parts[0] == 1 else version.parts[0]
                    jdk_version_string = version_output[2]
                    self._vm_info["platform.jdk-version-number"] = jdk_version_number
                    self._vm_info["platform.jdk-major-version"] = jdk_major_version
                    self._vm_info["platform.jdk-version-string"] = jdk_version_string
                else:
                    mx.log_error("VM info extraction failed ! (code={})".format(code))

    def dimensions(self, cwd, args, code, out):
        dims = super(OutputCapturingJavaVm, self).dimensions(cwd, args, code, out)
        if self._vm_info:
            dims.update(self._vm_info)
        return dims

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        """Runs JVM with the specified arguments stdout and stderr, and working dir."""
        raise NotImplementedError()

    def run_vm(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        self.extract_vm_info(args)
        return self.run_java(args=args, out=out, err=err, cwd=cwd, nonZeroIsFatal=nonZeroIsFatal)


class DefaultJavaVm(OutputCapturingJavaVm):
    def __init__(self, raw_name, raw_config_name):
        super(DefaultJavaVm, self).__init__()
        self.raw_name = raw_name
        self.raw_config_name = raw_config_name

    def name(self):
        return self.raw_name

    def config_name(self):
        return self.raw_config_name

    def post_process_command_line_args(self, args):
        return args

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        mx.get_jdk().run_java(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)


class DummyJavaVm(OutputCapturingJavaVm):
    """
    Dummy VM to work around: "pylint #111138 disabling R0921 does'nt work"
    https://www.logilab.org/ticket/111138

    Note that the warning R0921 (abstract-class-little-used) has been removed
    from pylint 1.4.3.
    """

def add_java_vm(javavm, suite=None, priority=0):
    java_vm_registry.add_vm(javavm, suite, priority)


def get_java_vm(vm_name, jvmconfig):
    return java_vm_registry.get_vm(vm_name, jvmconfig)


class TestBenchmarkSuite(JavaBenchmarkSuite):
    """Example suite used for testing and as a subclassing template.
    """
    def name(self):
        return "test"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"

    def validateReturnCode(self, retcode):
        return True

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        return bmSuiteArgs

    def benchmarkList(self, bmSuiteArgs):
        return ["simple-bench", "complex-bench"]

    def rules(self, out, benchmarks, bmSuiteArgs):
        return [
          StdOutRule(r"-d(?P<flag>[0-9]+)\s+use a (?P<bitnum>[0-9]+)-bit data model", {
            "benchmark": "test",
            "metric.better": "lower",
            "metric.name": "count",
            "metric.unit": "#",
            "extra.input-num": ("<flag>", int),
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

    def getJMHEntry(self, bmSuiteArgs):
        raise NotImplementedError()

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        vmArgs = self.vmArgs(bmSuiteArgs) + self.extraVmArgs()
        runArgs = self.extraRunArgs() + self.runArgs(bmSuiteArgs)
        return vmArgs + self.getJMHEntry(bmSuiteArgs) + ['--jvmArgsPrepend', ' '.join(vmArgs)] + runArgs + (benchmarks if benchmarks else [])

    def successPatterns(self):
        return [
            re.compile(
                r"# Run complete.",
                re.MULTILINE)
        ]

    def benchSuiteName(self, bmSuiteArgs):
        return self.name()

    def failurePatterns(self):
        return [re.compile(r"<failure>")]

    def flakySuccessPatterns(self):
        return []

    def rules(self, out, benchmarks, bmSuiteArgs):
        return [JMHJsonRule(JMHBenchmarkSuiteBase.jmh_result_file, self.benchSuiteName(bmSuiteArgs))]


class JMHDistBenchmarkSuite(JMHBenchmarkSuiteBase):
    """
    JMH benchmark suite that executes microbenchmark mx distribution.
    """

    def benchSuiteName(self, bmSuiteArgs):
        if self.dist:
            return "jmh-" + self.dist
        return super(JMHDistBenchmarkSuite, self).benchSuiteName(bmSuiteArgs)

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        if benchmarks is None:
            mx.abort("JMH Dist Suite requires a JMH distribution. (try {0}:*)".format(self.name()))
        if len(benchmarks) != 1:
            mx.abort("JMH Dist Suite runs only a single JMH distribution, got: {0}".format(benchmarks))
        self.dist = benchmarks[0]
        mx.log("running " + self.dist)
        return super(JMHDistBenchmarkSuite, self).createCommandLineArgs(None, bmSuiteArgs)

    def extraVmArgs(self):
        assert self.dist
        jdk = mx.get_jdk(mx.distribution(self.dist).javaCompliance)
        return mx.get_runtime_jvm_args([self.dist], jdk=jdk)

    def filter_distribution(self, dist):
        return any((dep.name.startswith('JMH') for dep in dist.archived_deps()))

    def benchmarkList(self, bmSuiteArgs):
        return [d.name
                for suite in self.benchmark_suites()
                for d in suite.dists
                if self.filter_distribution(d)
                ]

    def benchmark_suites(self):
        opt_limit_to_suite = True
        suites = mx.suites(opt_limit_to_suite, includeBinary=False)
        if mx.primary_suite() == mx._mx_suite:
            suites.append(mx._mx_suite)
        return suites

    def getJMHEntry(self, bmSuiteArgs):
        assert self.dist
        # JMHArchiveParticipant ensures that mainClass is set correctly
        return [mx.distribution(self.dist).mainClass]


class JMHRunnerBenchmarkSuite(JMHBenchmarkSuiteBase):
    """JMH benchmark suite that uses jmh-runner to execute projects with JMH benchmarks."""

    def benchmarkList(self, bmSuiteArgs):
        """Return all different JMH versions found."""
        return list(JMHRunnerBenchmarkSuite.get_jmh_projects_dict().keys())

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        if benchmarks is None:
            mx.abort("JMH Suite runs only a single JMH version.")
        if len(benchmarks) != 1:
            mx.abort("JMH Suite runs only a single JMH version, got: {0}".format(benchmarks))
        self._jmh_version = benchmarks[0]
        return super(JMHRunnerBenchmarkSuite, self).createCommandLineArgs([], bmSuiteArgs)

    def extraVmArgs(self):
        if not self._jmh_version:
            mx.abort("No JMH version selected!")
        jmhProjects = JMHRunnerBenchmarkSuite.get_jmh_projects_dict()[self._jmh_version]
        if not jmhProjects:
            mx.abort("No JMH benchmark projects found!")
        return mx.get_runtime_jvm_args([p.name for p in jmhProjects], jdk=mx.get_jdk())

    @staticmethod
    def get_jmh_projects_dict():
        # find all projects with a direct JMH dependency
        jmhProjects = {}
        projects = mx.projects_opt_limit_to_suites()
        if mx.primary_suite() == mx._mx_suite:
            projects = [p for p in mx._projects.values() if p.suite == mx._mx_suite]
        for p in projects:
            for x in p.deps:
                if x.name.startswith('JMH'):
                    if x.name not in jmhProjects:
                        jmhProjects[x.name] = []
                    jmhProjects[x.name].append(p)
        return jmhProjects

    def getJMHEntry(self, bmSuiteArgs):
        return ["org.openjdk.jmh.Main"]



class JMHJarBenchmarkSuite(JMHBenchmarkSuiteBase):
    """
    JMH benchmark suite that executes microbenchmarks in a JMH jar.

    This suite relies on the `--jmh-jar` and `--jmh-name` to be set. The former
    specifies the path to the JMH jar files. The later is the name suffix that is use
    for the bench-suite property.
    """
    jmh_jar_parser_name = "jmh_jar_benchmark_suite_vm"

    def benchmarkList(self, bmSuiteArgs):
        benchmarks = None
        jvm = self.getJavaVm(bmSuiteArgs)
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        args = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        _, out, _ = jvm.run(cwd, args + self.jmhBenchmarkFilter(bmSuiteArgs) + ["-l"])
        benchs = out.splitlines()
        linenumber = -1
        for linenumber in range(len(benchs)):
            if benchs[linenumber].startswith("Benchmarks:"):
                break
        assert linenumber >= 0, "No benchmarks output list found"
        return benchs[linenumber + 1:]

    def benchSuiteName(self, bmSuiteArgs):
        return "jmh-" + self.jmhName(bmSuiteArgs)

    def parserNames(self):
        return super(JMHJarBenchmarkSuite, self).parserNames() + [JMHJarBenchmarkSuite.jmh_jar_parser_name]

    def getJMHEntry(self, bmSuiteArgs):
        return ["-jar", self.jmhJAR(bmSuiteArgs)]

    def jmhArgs(self, bmSuiteArgs):
        vmAndSuiteArgs = self.vmAndRunArgs(bmSuiteArgs)[0]
        args, _ = get_parser(JMHJarBenchmarkSuite.jmh_jar_parser_name).parse_known_args(vmAndSuiteArgs)
        return args

    def jmhName(self, bmSuiteArgs):
        jmh_name = self.jmhArgs(bmSuiteArgs).jmh_name
        if jmh_name is None:
            mx.abort("Please use the --jmh-name benchmark suite argument to set the name of the JMH suite.")
        return jmh_name

    def jmhBenchmarkFilter(self, bmSuiteArgs):
        jmh_benchmarks = self.jmhArgs(bmSuiteArgs).jmh_benchmarks
        jmh_benchmarks = jmh_benchmarks if jmh_benchmarks is not None else ""
        return jmh_benchmarks.split(',')

    def jmhJAR(self, bmSuiteArgs):
        jmh_jar = self.jmhArgs(bmSuiteArgs).jmh_jar
        if jmh_jar is None:
            mx.abort("Please use the --jmh-jar benchmark suite argument to set the JMH jar file.")
        jmh_jar = os.path.expanduser(jmh_jar)
        if not os.path.exists(jmh_jar):
            mx.abort("The --jmh-jar argument points to a non-existing file: " + jmh_jar)
        return jmh_jar


class JMHRunnerMxBenchmarkSuite(JMHRunnerBenchmarkSuite):

    def alternative_suite(self):
        return "jmh-dist"

    def name(self):
        return "jmh-mx"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"


class JMHDistMxBenchmarkSuite(JMHDistBenchmarkSuite):
    def name(self):
        return "jmh-dist"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"


class JMHJarMxBenchmarkSuite(JMHJarBenchmarkSuite):
    def name(self):
        return "jmh-jar"

    def group(self):
        return "Graal"

    def subgroup(self):
        return "mx"


def build_number():
    """
    Get the current build number from the BUILD_NUMBER environment variable. If BUILD_NUMBER is not set or not a number,
    a default of -1 is returned.

    :return: the build number
    :rtype: int
    """
    build_num = mx.get_env("BUILD_NUMBER", default="-1")
    try:
        return int(build_num)
    except ValueError:
        mx.logv("Could not parse the build number from BUILD_NUMBER. Expected int, instead got: {0}".format(build_num))
        return -1


def build_name():
    """
    Get the current build name from the BUILD_NAME environment variable, or an empty string otherwise.

    :return: the build name
    :rtype: basestring
    """
    return mx.get_env("BUILD_NAME", default="")

def builder_url():
    """
    Get the builders url from the BUILD_URL environment variable, or an empty string otherwise.

    :return: the builders url
    :rtype: basestring
    """
    return mx.get_env("BUILD_URL", default="")


def build_url():
    """
    Get the current builder url. This method requires that both BUILD_NUMBER and BUILD_URL environment variables are
    set. If either the build number or the builder url cannot be retrieved an empty string is returned.

    :return: the build url
    :rtype: basestring
    """
    build_num = build_number()
    base_url = builder_url()
    if base_url and build_num != -1:
        return "{0}/builds/{1}".format(base_url, build_num)
    return ""


class BenchmarkExecutor(object):
    def uid(self):
        return str(uuid.uuid1())

    def group(self, suite):
        return suite.group()

    def buildFlags(self):
        return ""

    def machineArch(self):
        return mx.get_arch()

    def machinePlatform(self):
        return platform.platform()

    def machineCpuCores(self):
        return mx.cpu_count()

    def machineHostname(self):
        return socket.gethostname()

    def machineName(self, mxBenchmarkArgs):
        if mxBenchmarkArgs.machine_name:
            return mxBenchmarkArgs.machine_name
        return mx.get_env("MACHINE_NAME", default="")

    def machineNode(self, mxBenchmarkArgs):
        if mxBenchmarkArgs.machine_node:
            return mxBenchmarkArgs.machine_node
        return mx.get_env("MACHINE_NODE", default="")

    def machineIp(self, mxBenchmarkArgs):
        if mxBenchmarkArgs.machine_ip:
            return mxBenchmarkArgs.machine_ip
        return mx.get_env("NODE_NAME", default="")

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
        name = mxsuite.vc.active_branch(mxsuite.dir, abortOnError=False) if mxsuite.vc else '<unknown>'
        return name

    def buildUrl(self):
        return builder_url()

    def buildNumber(self):
        return build_number()

    def buildName(self):
        return build_name()

    def extras(self, mxBenchmarkArgs):
        extras = {}
        if mxBenchmarkArgs.extras:
            for kv in mxBenchmarkArgs.extras.split(","):
                split_kv = kv.split(":")
                if len(split_kv) != 2:
                    raise ValueError("Cannot handle extra '{}'. "
                                     "Extras key-value pairs must contain a single colon.".format(kv))
                k, v = split_kv
                if not re.match(r"^[\w\d\._-]*$", k):
                    raise ValueError("Extra key can only contain numbers, characters, underscores and dashes. "
                                     "Got '{}'".format(k))
                extras["extra.{}".format(k)] = v
        return extras

    def checkEnvironmentVars(self):
        pass

    def triggeringSuite(self, mxBenchmarkArgs):
        if mxBenchmarkArgs.triggering_suite:
            return mxBenchmarkArgs.triggering_suite
        return mx.get_env("TRIGGERING_SUITE", default=None)

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
          "machine.node": self.machineNode(mxBenchmarkArgs),
          "machine.ip": self.machineIp(mxBenchmarkArgs),
          "machine.hostname": self.machineHostname(),
          "machine.arch": self.machineArch(),
          "machine.cpu-cores": self.machineCpuCores(),
          "machine.cpu-clock": self.machineCpuClock(),
          "machine.cpu-family": self.machineCpuFamily(),
          "machine.ram": self.machineRam(),
          "extra.machine.platform": self.machinePlatform(),
          "branch": self.branch(),
          "build.url": self.buildUrl(),
          "build.number": self.buildNumber(),
          "build.job-name": self.buildName(),
          "metric.score-function": "id",
          "warnings": "",
        }

        standard.update(suite.suiteDimensions())
        standard.update(self.extras(mxBenchmarkArgs))

        def commit_info(prefix, mxsuite):
            vc = mxsuite.vc
            if vc is None:
                return {}
            info = vc.parent_info(mxsuite.dir)
            url = vc.default_pull(mxsuite.dir, abortOnError=False)
            if not url:
                url = "unknown"
            return {
              prefix + "commit.rev": vc.parent(mxsuite.dir),
              prefix + "commit.repo-url": url,
              prefix + "commit.author": info["author"],
              prefix + "commit.author-ts": info["author-ts"],
              prefix + "commit.committer": info["committer"],
              prefix + "commit.committer-ts": info["committer-ts"],
            }

        standard.update(commit_info("", mx.primary_suite()))
        for mxsuite in mx.suites():
            ignored = mxBenchmarkArgs.ignore_suite_commit_info
            if ignored and mxsuite.name in ignored:
                continue
            standard.update(commit_info(mxsuite.name + ".", mxsuite))
        triggering_suite = self.triggeringSuite(mxBenchmarkArgs)
        if triggering_suite:
            mxsuite = mx.suite(triggering_suite)
            standard.update(commit_info("extra.triggering-repo.", mxsuite))
        return standard

    def getSuiteAndBenchNames(self, args, bmSuiteArgs):
        argparts = args.benchmark.split(":")
        suitename = argparts[0]
        exclude = False
        if len(argparts) == 2:
            benchspec = argparts[1]
            if benchspec.startswith('~'):
                benchspec = benchspec[1:]
                exclude = True
        else:
            benchspec = ""
        suite = _bm_suites.get(suitename)
        if not suite:
            mx.abort("Cannot find benchmark suite '{0}'.  Available suites are: {1}".format(suitename, ' '.join(bm_suite_valid_keys())))
        if args.bench_suite_version:
            suite.setDesiredVersion(args.bench_suite_version)
        if benchspec == "*":
            return (suite, [[b] for b in suite.benchmarkList(bmSuiteArgs)])
        elif benchspec.startswith("*[") and benchspec.endswith("]"):
            all_benchmarks = suite.benchmarkList(bmSuiteArgs)
            requested_benchmarks = benchspec[2:-1].split(",")
            if not set(requested_benchmarks) < set(all_benchmarks):
                difference = list(set(requested_benchmarks) - set(all_benchmarks))
                plural = "" if len(difference) == 1 else "s"
                mx.abort("The benchmark{0} {1} are not supported by the suite ".format(plural, ",".join(difference)))
            return (suite, [[b] for b in all_benchmarks if b in requested_benchmarks])
        elif benchspec == "":
            return (suite, [None])
        else:
            benchspec = benchspec.split(",")
            benchmark_list = suite.benchmarkList(bmSuiteArgs)
            for bench in benchspec:
                if not bench in benchmark_list:
                    mx.abort("Cannot find benchmark '{0}' in suite '{1}'.  Available benchmarks are {2}".format(
                        bench, suitename, benchmark_list))
            if exclude:
                return (suite, [[bench] for bench in benchmark_list if bench not in benchspec])
            return (suite, [benchspec])

    def applyScoreFunction(self, datapoint):
        if not "metric.score-value" in datapoint:
            function = datapoint["metric.score-function"]
            # Determine the metric value, if one exists.
            metric_value = 0
            if "metric.value" in datapoint:
                metric_value = datapoint["metric.value"]
            # Apply the score function to the metric value.
            if function == "id":
                datapoint["metric.score-value"] = metric_value
            elif function.startswith("multiply(") and function.endswith(")"):
                factor = function[len("multiply("):-1]
                try:
                    factor = float(factor)
                except ValueError:
                    raise ValueError("'metric.score-function' multiply factor must be numerical ! "
                                     "Got '{}'".format(factor))
                datapoint["metric.score-value"] = float(metric_value) * factor
            else:
                mx.abort("Unknown score function '{0}'.".format(function))

    def add_fork_number(self, datapoint, fork_number):
        if 'metric.fork-number' not in datapoint:
            datapoint['metric.fork-number'] = fork_number

    def execute(self, suite, benchnames, mxBenchmarkArgs, bmSuiteArgs, fork_number=0):
        def postProcess(results):
            processed = []
            dim = self.dimensions(suite, mxBenchmarkArgs, bmSuiteArgs)
            for result in results:
                if not isinstance(result, dict):
                    result = result.__dict__
                point = dim.copy()
                point.update(result)
                self.applyScoreFunction(point)
                self.add_fork_number(point, fork_number)
                processed.append(point)
            return processed

        results = suite.run(benchnames, bmSuiteArgs)
        processedResults = postProcess(results)
        return processedResults

    def benchmark(self, mxBenchmarkArgs, bmSuiteArgs):
        """Run a benchmark suite."""
        parser = ArgumentParser(
            prog="mx benchmark",
            add_help=False,
            description=benchmark.__doc__,
            epilog="Note: parsers used by different suites have additional arguments, shown below.",
            usage="mx benchmark <options> -- <benchmark-suite-args> -- <benchmark-args>",
            formatter_class=RawTextHelpFormatter)
        parser.add_argument(
            "benchmark", nargs="?", default=None,
            help="Benchmark to run, format: <suite>:<benchmark>.")
        parser.add_argument(
            "--results-file",
            default="bench-results.json",
            help="Path to JSON output file with benchmark results.")
        parser.add_argument(
            "--bench-suite-version", default=None, help="Desired version of the benchmark suite to execute.")
        parser.add_argument(
            "--machine-name", default=None, help="Abstract name of the target machine.")
        parser.add_argument(
            "--machine-node", default=None, help="Machine node the benchmark is executed on.")
        parser.add_argument(
            "--machine-ip", default=None, help="Machine ip the benchmark is executed on.")
        parser.add_argument(
            "--triggering-suite", default=None,
            help="Name of the suite that triggered this benchmark, used to extract commit info of the corresponding repo.")
        parser.add_argument(
            "--ignore-suite-commit-info", default=None, type=lambda s: s.split(","),
            help="A comma-separated list of suite dependencies whose commit info must not be included.")
        parser.add_argument(
            "--extras", default=None, help="One or more comma separated key:value pairs to add to the results file.")
        parser.add_argument(
            "--list", default=None, action="store_true",
            help="Print the list of all available benchmark suites or all benchmarks available in a suite.")
        parser.add_argument(
            "--fork-count-file", default=None,
            help="Path to the file that lists the number of re-executions for the targeted benchmarks, using the JSON format: { (<name>: <count>,)* }")
        parser.add_argument(
            "-h", "--help", action="store_true", default=None,
            help="Show usage information.")
        mxBenchmarkArgs = parser.parse_args(mxBenchmarkArgs)

        suite = None
        if mxBenchmarkArgs.benchmark:
            # The suite will read the benchmark specifier,
            # and therewith produce a list of benchmark sets to run in separate forks.
            # Later, the harness passes each set of benchmarks from this list to the suite separately.
            suite, benchNamesList = self.getSuiteAndBenchNames(mxBenchmarkArgs, bmSuiteArgs)

        if mxBenchmarkArgs.list:
            if mxBenchmarkArgs.benchmark and suite:
                print("The following benchmarks are available in suite {}:\n".format(suite.name()))
                for name in suite.benchmarkList(bmSuiteArgs):
                    print("  " + name)
                if isinstance(suite.get_vm_registry(), VmBenchmarkSuite):
                    print("\n{}".format(suite.get_vm_registry().get_available_vm_configs_help()))
            else:
                vmregToSuites = {}
                noVmRegSuites = []
                for bm_suite_name, bm_suite in sorted([(k, v) for k, v in _bm_suites.items() if v]):
                    if isinstance(bm_suite, VmBenchmarkSuite):
                        vmreg = bm_suite.get_vm_registry()
                        vmregToSuites.setdefault(vmreg, []).append(bm_suite_name)
                    else:
                        noVmRegSuites.append(bm_suite_name)
                for vmreg, bm_suite_names in vmregToSuites.items():
                    print("\nThe following {} benchmark suites are available:\n".format(vmreg.vm_type_name))
                    for name in bm_suite_names:
                        print("  " + name)
                    print("\n{}".format(vmreg.get_available_vm_configs_help()))
                if noVmRegSuites:
                    print("\nThe following non-VM benchmark suites are available:\n")
                    for name in noVmRegSuites:
                        print("  " + name)
            return 0

        if mxBenchmarkArgs.help or mxBenchmarkArgs.benchmark is None:
            parser.print_help()
            for key, entry in parsers.items():
                if mxBenchmarkArgs.benchmark is None or key in suite.parserNames():
                    print(entry.description)
                    entry.parser.print_help()
            for vmreg in vm_registries():
                print("\n{}".format(vmreg.get_available_vm_configs_help()))
            return 0 if mxBenchmarkArgs.help else 1

        self.checkEnvironmentVars()

        results = []

        # The fork-counts file can be used to specify how many times to repeat the whole fork of the benchmark.
        # For simplicity, this feature is only supported if the benchmark harness invokes each benchmark in the suite separately
        # (i.e. when the harness does not ask the suite to run a set of benchmarks within the same process).
        fork_count_spec = None
        if mxBenchmarkArgs.fork_count_file:
            with open(mxBenchmarkArgs.fork_count_file) as f:
                fork_count_spec = json.load(f)
        failures_seen = False
        try:
            suite.before(bmSuiteArgs)
            start_time = time.time()
            for benchnames in benchNamesList:
                suite.validateEnvironment()
                fork_count = 1
                if fork_count_spec and benchnames and len(benchnames) == 1:
                    fork_count = fork_count_spec.get("{}:{}".format(suite.name(), benchnames[0]), fork_count_spec.get(benchnames[0]))
                elif fork_count_spec and len(suite.benchmarkList(bmSuiteArgs)) == 1:
                    # single benchmark suites executed by providing the suite name only or a wildcard
                    fork_count = fork_count_spec.get(suite.name(), fork_count_spec.get("{}:*".format(suite.name())))
                elif fork_count_spec:
                    mx.abort("The fork-count feature is only supported when the suite is asked to run a single benchmark within a fork.")
                if fork_count_spec and fork_count is None:
                    fork_count = 1
                    mx.log("Defaulting fork count to 1 for {}:{} since there is no value for it in the fork count file.".format(suite.name(), benchnames[0]))
                for fork_num in range(0, fork_count):
                    if fork_count_spec:
                        mx.log("Execution of fork {}/{}".format(fork_num + 1, fork_count))
                    try:
                        partialResults = self.execute(
                            suite, benchnames, mxBenchmarkArgs, bmSuiteArgs, fork_number=fork_num)
                        results.extend(partialResults)
                    except (BenchmarkFailureError, RuntimeError):
                        failures_seen = True
                        mx.log(traceback.format_exc())
            end_time = time.time()
        finally:
            try:
                suite.after(bmSuiteArgs)
            except RuntimeError:
                failures_seen = True


        for result in results:
            result["benchmarking.start-ts"] = int(start_time)
            result["benchmarking.end-ts"] = int(end_time)

        topLevelJson = {
          "queries": results
        }
        dump = json.dumps(topLevelJson, sort_keys=True, indent=2)
        with open(mxBenchmarkArgs.results_file, "w") as txtfile:
            txtfile.write(dump)
        if failures_seen:
            mx.log_error("Failures happened during benchmark(s) execution !")
            return 1
        return 0


_benchmark_executor = BenchmarkExecutor()


def init_benchmark_suites():
    """Called after mx initialization if mx is the primary suite."""
    add_java_vm(DefaultJavaVm("server", "default"), priority=-1)
    add_bm_suite(JMHRunnerMxBenchmarkSuite())
    add_bm_suite(JMHDistMxBenchmarkSuite())
    add_bm_suite(JMHJarMxBenchmarkSuite())
    add_bm_suite(TestBenchmarkSuite())


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

def rsplitArgs(args, separator):
    """Splits the list of string arguments at the last separator argument.

    :param list args: List of arguments.
    :param str separator: Argument that is considered a separator.
    :return: A tuple with the list of arguments before and a list after the separator.
    :rtype: tuple
    """
    rafter, rbefore = splitArgs(list(reversed(args)), separator)
    return list(reversed(rbefore)), list(reversed(rafter))


def benchmark(args):
    """Run benchmark suite with given name.

    :Example:

        mx benchmark bmSuiteName[:benchName] [mxBenchmarkArgs] -- [bmSuiteArgs]
        mx benchmark --help

    :param list args:
        List of arguments (see below).

        `bmSuiteName`: Benchmark suite name (e.g. `dacapo`, `octane`, `specjvm08`, ...).
        `benchName`: Name of particular benchmark within the benchmark suite
            (e.g. `raytrace`, `deltablue`, `avrora`, ...), or a wildcard indicating that
            all the benchmarks need to be executed as separate runs. If omitted, all the
            benchmarks must be executed as part of one run. If `benchName` starts with
            `~`, then all the specified benchmarks are excluded and the unspecified
            benchmarks are executed as part of one run.
            If a wildcard with a `*[bench1,bench2,...]` list is specified,
            then only the subset of the benchmarks from the list is run.
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
