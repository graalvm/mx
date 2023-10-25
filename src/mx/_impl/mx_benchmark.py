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

__all__ = [
    "mx_benchmark_compatibility",
    "JVMProfiler",
    "register_profiler",
    "SimpleJFRProfiler",
    "AsyncProfiler",
    "ParserEntry",
    "parsers",
    "add_parser",
    "get_parser",
    "VmRegistry",
    "BenchmarkSuite",
    "add_bm_suite",
    "bm_suite_valid_keys",
    "vm_registries",
    "Rule",
    "BaseRule",
    "StdOutRule",
    "CSVBaseRule",
    "CSVFixedFileRule",
    "CSVStdOutFileRule",
    "JsonBaseRule",
    "JsonStdOutFileRule",
    "JsonFixedFileRule",
    "JMHJsonRule",
    "BenchmarkFailureError",
    "StdOutBenchmarkSuite",
    "DeprecatedMixin",
    "AveragingBenchmarkMixin",
    "WarnDeprecatedMixin",
    "VmBenchmarkSuite",
    "JavaBenchmarkSuite",
    "TemporaryWorkdirMixin",
    "Vm",
    "GuestVm",
    "JavaVm",
    "java_vm_registry",
    "js_vm_registry",
    "OutputCapturingVm",
    "OutputCapturingJavaVm",
    "DefaultJavaVm",
    "DummyJavaVm",
    "add_java_vm",
    "get_java_vm",
    "TestBenchmarkSuite",
    "JMeterBenchmarkSuite",
    "JMHBenchmarkSuiteBase",
    "JMHJarBasedBenchmarkSuiteBase",
    "JMHDistBenchmarkSuite",
    "JMHRunnerBenchmarkSuite",
    "JMHJarBenchmarkSuite",
    "JMHRunnerMxBenchmarkSuite",
    "JMHDistMxBenchmarkSuite",
    "JMHJarMxBenchmarkSuite",
    "build_number",
    "build_name",
    "builder_url",
    "build_url",
    "enable_tracker",
    "disable_tracker",
    "Tracker",
    "RssTracker",
    "PsrecordTracker",
    "PsrecordMaxrssTracker",
    "BenchmarkExecutor",
    "make_hwloc_bind",
    "init_benchmark_suites",
    "splitArgs",
    "rsplitArgs",
    "benchmark",
    "OutputDump",
    "TTYCapturing",
    "gate_mx_benchmark",
]

import sys
import json
import os.path
import platform
import re
import socket
import time
import traceback
import uuid
import tempfile
import shutil
import zipfile
import shlex
from argparse import ArgumentParser
from argparse import RawTextHelpFormatter
from argparse import SUPPRESS
from collections import OrderedDict

from . import mx

_bm_suites = {}
_benchmark_executor = None


def mx_benchmark_compatibility():
    """Get the required compatibility version from the mx primary suite.

    :rtype: MxCompatibility500
    """
    return mx.primary_suite().getMxCompatibility()


_profilers = {}


class JVMProfiler(object):
    """
    Encapsulates the name and how to trigger common VM profilers.
    """
    def __init__(self):
        self.nextItemName = None

    def name(self):
        raise NotImplementedError()

    def setup(self, benchmarks, bmSuiteArgs):
        if benchmarks:
            self.nextItemName = benchmarks[0]
        else:
            self.nextItemName = None

    def sets_vm_prefix(self):
        return False

    def additional_options(self, dump_path):
        """
        Returns a tuple of a list extra JVM options to be added to the command line, plus an optional
        set of arguments that will be inserted as a command prefix.
        """
        return [], None


def register_profiler(obj):
    if not isinstance(obj, JVMProfiler):
        raise ValueError(f"Cannot register profiler. Profilers must be of type {JVMProfiler.__class__.__name__}")
    if obj.name() in _profilers:
        raise ValueError("A profiler with name '{}' is already registered!")
    _profilers[obj.name()] = obj


class SimpleJFRProfiler(JVMProfiler):
    """
    A simple JFR profiler with reasonable defaults.
    """
    def name(self):
        return "JFR"

    def additional_options(self, dump_path):
        if self.nextItemName:
            import datetime
            filename = os.path.join(dump_path, f"{self.nextItemName}_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.jfr")
        else:
            filename = dump_path

        common_opts = [
            "-XX:+UnlockDiagnosticVMOptions",
            "-XX:+DebugNonSafepoints",
            "-XX:+FlightRecorder"
        ]
        if mx.get_jdk().javaCompliance >= '9':
            opts = common_opts + [
                f"-XX:StartFlightRecording=settings=profile,disk=false,maxsize=200M,dumponexit=true,filename={filename}",
                "-Xlog:jfr=info"
            ]
        elif mx.get_jdk().is_openjdk_based():
            # No logging levels on OpenJDK 8.
            # Alternatively, one can use -XX:+LogJFR for 'trace' level
            opts = common_opts + [
                "-XX:+UnlockCommercialFeatures",
                f"-XX:StartFlightRecording=settings=profile,disk=false,maxsize=200M,dumponexit=true,filename={filename}"
            ]
        else:
            opts = ["-XX:+UnlockCommercialFeatures"] + common_opts + [
                f"-XX:StartFlightRecording=defaultrecording=true,settings=profile,filename={filename}",
                "-XX:FlightRecorderOptions=loglevel=info,disk=false,maxsize=200M,dumponexit=true"
            ]

        # reset the next item name since it has just been consumed
        self.nextItemName = None
        return opts, None


class AsyncProfiler(JVMProfiler):
    """
    Produces svg flame graphs using async-profiler (https://github.com/jvm-profiling-tools/async-profiler)
    """
    def name(self):
        return "async"

    def version(self):
        return "1.8.3"

    def libraryPath(self):
        async_profiler_lib = mx.library(f"ASYNC_PROFILER_{self.version()}")
        if not async_profiler_lib.is_available():
            mx.abort(f"'--profiler {self.name()}' is not supported on '{mx.get_os()}/{mx.get_arch()}' because the '{async_profiler_lib.name}' library is not available.")

        libraryDirectory = async_profiler_lib.get_path(True)
        innerDir = [f for f in os.listdir(libraryDirectory) if os.path.isdir(os.path.join(libraryDirectory, f))][0]
        return os.path.join(libraryDirectory, innerDir, "build", "libasyncProfiler.so")

    def additional_options(self, dump_path):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        if self.nextItemName:
            filename = os.path.join(dump_path, f"{self.nextItemName}_{timestamp}.svg")
        else:
            filename = os.path.join(dump_path, f"{timestamp}.svg")

        opts = [f"-agentpath:{self.libraryPath()}=start,file={filename}"]

        # reset the next item name since it has just been consumed
        self.nextItemName = None
        return opts, None


register_profiler(SimpleJFRProfiler())
register_profiler(AsyncProfiler())


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
        mx.abort(f"There is already a parser called '{name}'")
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
            f"\n\n{self.vm_type_name} selection flags, specified in the benchmark suite arguments:\n"
        ))
        get_parser(self.get_parser_name()).add_argument("--profiler", default=None, help="The profiler to use")
        get_parser(self.get_parser_name()).add_argument(f"--{self.short_vm_type_name}", default=None, help=f"{self.vm_type_name} to run the benchmark with.")
        get_parser(self.get_parser_name()).add_argument(f"--{self.short_vm_type_name}-config", default=None, help=f"{self.vm_type_name} configuration for the selected {self.vm_type_name}.")
        # Separator to stack guest and host VM options. Though ignored, must be consumed by the parser.
        get_parser(self.get_parser_name()).add_argument('--guest', action='store_true', dest=SUPPRESS, default=None, help=f'Separator for --{self.short_vm_type_name}=host --guest --{self.short_vm_type_name}=guest VM configurations.')

    def get_parser_name(self):
        return self.vm_type_name + "_parser"

    def get_known_guest_registries(self):
        return self._known_host_registries

    def get_default_vm(self, config):
        if self.default_vm:
            return self.default_vm(config, self._vms)
        return None

    def get_available_vm_configs_help(self):
        avail = [f'--{self.short_vm_type_name}={vm.name()} --{self.short_vm_type_name}-config={vm.config_name()}' for vm in self._vms.values()]
        return f'The following {self.vm_type_name} configurations are available:\n  {os.linesep.join(avail)}'

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
                    mx.abort(f"Could not find a {self.vm_type_name} to default to.\n{self.get_available_vm_configs_help()}")
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
                    notice(f"Defaulting the {self.vm_type_name} to '{vm}'. Consider using --{self.short_vm_type_name} {choice}")
        if vm_config is None:
            vm_configs = [(config,
                            self._vms_suite[(vm, config)] == mx.primary_suite(),
                            ('hosted' in config) == hosted,
                            self._vms_priority[(vm, config)]
                            ) for (j, config) in self._vms if j == vm]
            if not vm_configs:
                mx.abort(f"Could not find a {self.vm_type_name} config to default to for {self.vm_type_name} '{vm}'.\n{self.get_available_vm_configs_help()}")
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
                notice(f"Defaulting the {self.vm_type_name} config to '{vm_config}'. Consider using --{self.short_vm_type_name}-config {choice}.")
        vm_object = self.get_vm(vm, vm_config)

        if check_guest_vm and not isinstance(vm_object, GuestVm):
            mx.abort(f"{self.vm_type_name} '{vm}' with config '{vm_config}' is declared as --guest but it's NOT a guest VM.")

        if isinstance(vm_object, GuestVm):
            host_vm = vm_object.hosting_registry().get_vm_from_suite_args(bmSuiteArgsPending, hosted=True, quiet=quiet, host_vm_only_as_default=True)
            vm_object = vm_object.with_host_vm(host_vm)
        return vm_object

    def add_vm(self, vm, suite=None, priority=0):
        key = (vm.name(), vm.config_name())
        if key in self._vms:
            mx.abort(f"{self.vm_type_name} and config '{key}' already exist.")
        self._vms[key] = vm
        self._vms_suite[key] = suite
        self._vms_priority[key] = priority

    def get_vm(self, vm_name, vm_config):
        key = (vm_name, vm_config)
        if key not in self._vms:
            mx.abort(f"{self.vm_type_name} and config '{key}' do not exist.\n{self.get_available_vm_configs_help()}")
        return self._vms[key]

    def get_vms(self):
        return list(self._vms.values())


class BenchmarkSuite(object):
    """
    A harness for a benchmark suite.

    A suite needs to be registered with mx_benchmarks.add_bm_suite.
    """
    def __init__(self, *args, **kwargs):
        super(BenchmarkSuite, self).__init__(*args, **kwargs)
        self._desired_version = None
        self._suite_dimensions = {}
        self._command_mapper_hooks = []
        self._trackers = []
        self._currently_running_benchmark = None

    def name(self):
        """Returns the name of the suite to execute.

        :return: Name of the suite.
        :rtype: str
        """
        raise NotImplementedError()

    def benchSuiteName(self, bmSuiteArgs=None):
        """Returns the name of the actual suite that is being executed, independent of the fact it's a suite variant
        which is configured or compiled differently.

        Example:
            - `benchSuiteName`: 'dacapo'
            - `name`: 'dacapo-timing' or 'dacapo-native-image'

        :return: Name of the suite.
        :rtype: str
        """
        return self.name()

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
        """Returns the list of the benchmarks of this suite which can be executed on the current host.

        An host in this context is the combination of OS, architecture, JDK version and any other system or
        configuration characteristics which impact the feasibility of running a given benchmark.

        :param list[str] bmSuiteArgs: List of string arguments to the suite.
        :return: List of benchmark string names.
        :rtype: list[str]
        """
        raise NotImplementedError()

    def completeBenchmarkList(self, bmSuiteArgs):
        """
        The name of all benchmarks of the suite independently of their support on the current host.
        :param list[str] bmSuiteArgs: List of string arguments to the suite.
        :return: List of benchmark names.
        :rtype: list[str]
        """
        return self.benchmarkList(bmSuiteArgs)

    def currently_running_benchmark(self):
        """
        :return: The name of the benchmark being currently executed or None otherwise.
        """
        return self._currently_running_benchmark

    def register_command_mapper_hook(self, name, func):
        """Registers a function that takes as input the benchmark suite object and the command to execute and returns
        a modified command line.

        :param function func:
        :return: None
        """
        self._command_mapper_hooks.append((name, func, self))

    def register_tracker(self, name, tracker_type):
        tracker = tracker_type(self)
        self._trackers.append(tracker)

        def hook(cmd, suite):
            assert suite == self
            return tracker.map_command(cmd)
        self.register_command_mapper_hook(name, hook)

    def version(self):
        """The suite version selected for execution which is either the :defaultSuiteVerion:
        or the :desiredVersion: if any.

        NOTE: This value is present in the result file for suite identification.

        :return: actual version.
        :rtype: str
        """
        if self.desiredVersion() and self.desiredVersion() not in self.availableSuiteVersions():
            mx.abort(f"Available suite versions are: {self.availableSuiteVersions()}")

        return self.desiredVersion() if self.desiredVersion() else self.defaultSuiteVersion()

    def defaultSuiteVersion(self):
        """ The default benchmark version to use.

        :return: default version.
        :rtype: str
        """
        return "unknown"

    def isDefaultSuiteVersion(self):
        """ Returns whether the selected version is the default benchmark suite version.

        :return: if the current suite version is the default one.
        :rtype: bool
        """
        return len(self.availableSuiteVersions()) <= 1 or self.version() == self.defaultSuiteVersion()

    def availableSuiteVersions(self):
        """List of available versions of that benchmark suite.

        :return: list of version strings.
        :rtype: list[str]
        """
        return [self.defaultSuiteVersion()] if self.defaultSuiteVersion() != "unknown" else []

    def desiredVersion(self):
        """Returns the benchmark suite version that is requested for execution.

        :return: suite version.
        :rtype: str
        """
        return self._desired_version

    def setDesiredVersion(self, version):
        if len(self.availableSuiteVersions()) <= 1:
            mx.abort("The suite is not versioned. So one cannot explicitly request a suite version.")
        if version not in self.availableSuiteVersions():
            mx.abort(f"Version '{version}' unknown! Available suite versions are: {self.availableSuiteVersions()}")
        self._desired_version = version

    def validateEnvironment(self):
        """Validates the environment and raises exceptions if validation fails.

        Can be overridden to check for existence of required environment variables
        before the benchmark suite executed.
        """
        pass

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

    def dump_results_file(self, file_path, data_points):
        if not data_points:
            data_points = []
        dump = json.dumps({"queries": data_points}, sort_keys=True, indent=2)
        with open(file_path, "w") as txtfile:
            txtfile.write(dump)
        file_size_kb = int(os.path.getsize(file_path) / 1024)
        mx.log(f"{len(data_points)} benchmark data points dumped to {file_path} ({file_size_kb} KB)")
        return len(data_points)

    def workingDirectory(self, benchmarks, bmSuiteArgs):
        """Returns the desired working directory for running the benchmark.

        By default it returns `None`, meaning that the working directory is not be
        changed. It is meant to be overridden in subclasses when necessary.
        """
        return None

    def expandBmSuiteArgs(self, benchmarks, bmSuiteArgs):
        """ Generates an arbitrary number of bmSuiteArgs variants to allow triggering multiple runs with different configurations.

        By default it returns the given a list only containing bmSuiteArgs.  If
        one needs a suite to be able to support a "generic" suite arugment,
        e.g. let's assume we have a bench suite called "mySuite" which can run
        individual benchmarks in multiple configs (interpreter, compiled,
        precompiled). We want to be able to do

        mx benchmark mySuite:* -- --mode=*

        to run the suite in all available modes. Overriding this method will allow expanding the
        "--mode=*"
        to
        ["--mode=interpreter", "--mode=compiled", "--mode=precompiled"]
        resulting in the benchmark being executed 3 times with these 3 arguments passed in as bmSuiteArgs.

        :returns: A list of arguments resulting from the expansion of bmSuiteArgs.

        """
        return [bmSuiteArgs]



def add_bm_suite(suite, mxsuite=None):
    if mxsuite is None:
        mxsuite = mx.currently_loading_suite.get()

    full_name = f"{suite.name()}-{suite.subgroup()}"
    if full_name in _bm_suites:
        raise RuntimeError(f"Benchmark suite full name '{full_name}' already exists.")
    _bm_suites[full_name] = suite
    setattr(suite, ".mxsuite", mxsuite)

    simple_name = suite.name()
    # If possible also register suite with simple_name
    if simple_name in _bm_suites:
        if _bm_suites[simple_name]:
            mx.log(f"Warning: Benchmark suite '{simple_name}' name collision. Suites only available as '{simple_name}-<subgroup>'.")
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
        """Create a dictionary of variables for every measurement.

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
        for every measurement.

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
                            raise RuntimeError(f"Unknown var {name}")
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
                        raise RuntimeError(f"Cannot handle object '{v}' of expected type {vtype}")
                if not isinstance(inst, (str, int, float, bool)):
                    if type(inst).__name__ != 'long': # Python2: int(x) can result in a long
                        raise RuntimeError(f"Object '{inst}' has unknown type: {type(inst)}")
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


class JsonBaseRule(BaseRule):
    """Parses JSON files and creates a measurement result using the replacement."""

    def __init__(self, replacement, keys):
        super(JsonBaseRule, self).__init__(replacement)
        self.keys = keys

    def parseResults(self, text):
        l = []
        for f in self.getJsonFiles(text):
            mx.logv(f"Parsing results using '{self.__class__.__name__}' on file: {f}")
            with open(f) as fp:
                l = l + [{k: str(v)} for k, v in json.load(fp).items() if k in self.keys]
        return l

    def getJsonFiles(self, text):
        """Get the JSON files which should be parsed.

       :param text: The standard output of the benchmark.
       :type text: str
       :return: List of file names
       :rtype: list
       """
        raise NotImplementedError()


class JsonStdOutFileRule(JsonBaseRule):
    """Rule that looks for JSON file names in the output of the benchmark."""

    def __init__(self, pattern, match_name, replacement, keys):
        super(JsonStdOutFileRule, self).__init__(replacement, keys)
        self.pattern = pattern
        self.match_name = match_name

    def getJsonFiles(self, text):
        return (m.groupdict()[self.match_name] for m in re.finditer(self.pattern, text, re.MULTILINE))


class JsonFixedFileRule(JsonBaseRule):
    """Rule that parses a JSON file with a predefined name."""

    def __init__(self, filename, replacement, keys):
        super(JsonFixedFileRule, self).__init__(replacement, keys)
        self.filename = filename

    def getJsonFiles(self, text):
        return [self.filename]


class JMHJsonRule(Rule):
    """Parses a JSON file produced by JMH and creates a measurement result."""

    extra_jmh_keys = [
        # parsed from the JMH JSON file
        "mode",
        "threads",
        "forks",
        "warmupIterations",
        "warmupTime",
        "warmupBatchSize",
        "measurementIterations",
        "measurementTime",
        "measurementBatchSize",

        # set via extra_bench_properties
        "mx-individual-run-mode",
        ]

    def __init__(self, filename, suiteName, extra_bench_properties=None):
        self.filename = filename
        self.suiteName = suiteName
        if extra_bench_properties is None:
            extra_bench_properties = {}
        self.extra_bench_properties = extra_bench_properties

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
                        raise RuntimeError(f"Unknown benchmark mode {mode}")

                d = {
                    "bench-suite" : self.suiteName,
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

                extra_properties = self.extra_bench_properties
                if "mx-individual-run-mode" not in extra_properties:
                    run_mode = "jmh-forking" if int(result["forks"]) >= 1 else "disabled"
                    extra_properties["mx-individual-run-mode"] = run_mode

                for k in self.getExtraJmhKeys():
                    extra_value = None
                    if k in result:
                        extra_value = result[k]
                    elif k in extra_properties:
                        extra_value = extra_properties[k]
                    d["extra.jmh." + k] = str(extra_value)

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
        retcode, out, dims = self.runAndReturnStdOut(benchmarks, bmSuiteArgs)
        datapoints = self.validateStdoutWithDimensions(out, benchmarks, bmSuiteArgs, retcode=retcode, dims=dims)
        return datapoints

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
            mx.warn(f"Benchmark skipped, flaky pattern found. Benchmark(s): {benchmarks}")
            return []

        datapoints = []
        rules = self.rules(out, benchmarks, bmSuiteArgs)
        for t in self._trackers:
            rules += t.get_rules(bmSuiteArgs)
        rules += extraRules

        for rule in rules:
            # pass working directory to rule without changing the signature of parse
            rule._cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
            parsedpoints = rule.parse(out)
            for datapoint in parsedpoints:
                datapoint.update(dims)
                if "bench-suite" not in datapoint:
                    datapoint["bench-suite"] = self.name()
                if "bench-suite-version" not in datapoint:
                    datapoint["bench-suite-version"] = self.version()
                if "is-default-bench-suite-version" not in datapoint:
                    datapoint["is-default-bench-suite-version"] = str(self.isDefaultSuiteVersion()).lower()
            datapoints.extend(parsedpoints)

        flaky = False
        for pat in self.flakySuccessPatterns():
            if compiled(pat).search(out):
                flaky = True
        if not flaky:
            if retcode is not None:
                if not self.validateReturnCode(retcode):
                    self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                        f"Benchmark failed, exit code: {retcode}")
            for pat in self.failurePatterns():
                m = compiled(pat).search(out)
                if m:
                    self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                        f"Benchmark failed, failure pattern found: '{m.group()}'. Benchmark(s): {benchmarks}")
            success = False
            for pat in self.successPatterns():
                if compiled(pat).search(out):
                    success = True
            if len(self.successPatterns()) == 0:
                success = True
            if not success:
                self.repairDatapointsAndFail(benchmarks, bmSuiteArgs, datapoints,
                    f"Benchmark failed, success pattern not found. Benchmark(s): {benchmarks}")

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
        msg = f"The `{self.name()}` benchmark suite is deprecated! {f'Consider using `{alternative_suite}` instead.' if alternative_suite else '(No alternatives provided.)'}"
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
                    mx.warn(f"Iteration results : {warmupResults}")

                if len(warmupResultsToAverage) != resultIterations:
                    mx.warn("Inconsistent number of iterations !")
                    mx.warn(f"Expecting {len(warmupResultsToAverage)} iterations, but got {resultIterations} instead.")
                    mx.warn(f"Iteration results : {warmupResults}")

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

        if self.profilerNames(bmSuiteArgs):
            for profiler in self.profilerNames(bmSuiteArgs).split(','):
                if profiler not in _profilers:
                    mx.abort(f"Unknown profiler '{profiler}'. Use one of: ({', '.join(_profilers.keys())})")
                vmargs, prefix_command = _profilers.get(profiler).additional_options(os.getcwd())
                args += vmargs
                if prefix_command:
                    # build a command mapper hook that inserts the prefix_command
                    assert _profilers.get(profiler).sets_vm_prefix()

                    def func(cmd, bmSuite, prefix_command=prefix_command):
                        return prefix_command + cmd
                    if self._command_mapper_hooks and profiler not in self._command_mapper_hooks[0]:
                        mx.abort(f"Profiler '{profiler}' conflicts with trackers '{', '.join([n for n, _, _ in self._command_mapper_hooks])}'\nUse --tracker none to disable all trackers")
                    self._command_mapper_hooks = [(profiler, func, self)]
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

    def profilerNames(self, bmSuiteArgs):
        return None

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        return self.createVmCommandLineArgs(benchmarks, self.runArgs(bmSuiteArgs))

    def createVmCommandLineArgs(self, benchmarks, runArgs):
        """" Creates the arguments that need to be passed to the VM to run the benchmarks.
        :rtype: list
        """
        raise NotImplementedError()

    def setupProfilers(self, benchmarks, bmSuiteArgs):
        if self.profilerNames(bmSuiteArgs) is not None:
            for profilerName in self.profilerNames(bmSuiteArgs).split(','):
                profiler = _profilers.get(profilerName)
                if profiler:
                    profiler.setup(benchmarks, bmSuiteArgs)

    def _vmRun(self, vm, workdir, command, benchmarks, bmSuiteArgs):
        """Executes `command` on `vm` in `workdir`. A benchmark suite can override this method if its execution is
        more complicated than a VM command line.

        :param Vm vm: the Vm to use to execute the command
        :param str workdir: the working directory for command execution
        :param list[str] benchmarks: the benchmarks to execute
        :param list[str] bmSuiteArgs: the command line options passed to mx benchmark
        :rtype: tuple
        """
        return vm.runWithSuite(self, workdir, command)

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        self.setupProfilers(benchmarks, bmSuiteArgs)
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs) or '.'
        command = self.createCommandLineArgs(benchmarks, bmSuiteArgs)
        if command is None:
            return 0, "", {}
        vm = self.get_vm_registry().get_vm_from_suite_args(bmSuiteArgs)
        vm.extract_vm_info(self.vmArgs(bmSuiteArgs))
        vm.command_mapper_hooks = self._command_mapper_hooks
        t = self._vmRun(vm, cwd, command, benchmarks, bmSuiteArgs)
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
                    mx.warn(f"VM {vm.name()}:{vm.config_name()} ({vm.__class__.__name__}) tried overwriting {key}='{dims[key]}' with '{value}', keeping '{dims[key]}'")
                    continue
                mx.warn(f"VM {vm.name()}:{vm.config_name()} ({vm.__class__.__name__}) is overwriting {key}='{dims[key]}' with '{value}'")
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
        return args.jvm, args.jvm_config, args.profiler, remainder

    def jvm(self, bmSuiteArgs):
        """Returns the value of the `--jvm` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[0]

    def jvmConfig(self, bmSuiteArgs):
        """Returns the value of the `--jvm-config` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[1]

    def profilerNames(self, bmSuiteArgs):
        """Returns the value of the `--profiler` argument or `None` if not present."""
        return self.splitJvmConfigArg(bmSuiteArgs)[2]

    def getJavaVm(self, bmSuiteArgs):
        return java_vm_registry.get_vm_from_suite_args(bmSuiteArgs)


class TemporaryWorkdirMixin(VmBenchmarkSuite):
    """This mixin provides a simple way for a benchmark suite to use a new temporary directory for the duration of the
    benchmark execution. The directory is automatically deleted at the end of the execution unless the benchmark failed
    or the --keep-scratch parameter was passed.

    To use this mechanism, a benchmark suite implementer must use `self.workingDirectory()` as the working
    directory for its command executions.
    """
    def before(self, bmSuiteArgs):
        parser = parsers["temporary_workdir_parser"].parser
        bmArgs, otherArgs = parser.parse_known_args(bmSuiteArgs)
        self.keepScratchDir = bmArgs.keep_scratch
        self.scratchDirectories = []
        if not bmArgs.no_scratch:
            self._create_tmp_workdir()
        else:
            mx.warn("NO scratch directory created! (--no-scratch)")
            self.workdir = None
        super(TemporaryWorkdirMixin, self).before(otherArgs)

    def _create_tmp_workdir(self):
        self.workdir = tempfile.mkdtemp(prefix=self.name() + '-work.', dir='.')

    def workingDirectory(self, benchmarks, bmSuiteArgs):
        return self.workdir

    def scratchDirs(self):
        return self.scratchDirectories

    def after(self, bmSuiteArgs):
        if hasattr(self, "keepScratchDir") and self.keepScratchDir:
            mx.warn(f"Scratch directory NOT deleted (--keep-scratch): {self.workdir}")
            self.scratchDirectories.append(os.path.abspath(self.workdir))
        elif self.workdir:
            shutil.rmtree(self.workdir)
        super(TemporaryWorkdirMixin, self).after(bmSuiteArgs)

    def repairDatapointsAndFail(self, benchmarks, bmSuiteArgs, partialResults, message):
        try:
            super(TemporaryWorkdirMixin, self).repairDatapointsAndFail(benchmarks, bmSuiteArgs, partialResults, message)
        finally:
            if self.workdir:
                # keep old workdir for investigation, create a new one for further benchmarking
                mx.warn(f"Keeping scratch directory after failed benchmark: {self.workdir}")
                self.scratchDirectories.append(os.path.abspath(self.workdir))
                self._create_tmp_workdir()

    def parserNames(self):
        return super(TemporaryWorkdirMixin, self).parserNames() + ["temporary_workdir_parser"]


def _create_temporary_workdir_parser():
    parser = ArgumentParser(add_help=False, usage=_mx_benchmark_usage_example + " -- <options> -- ...")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--keep-scratch", action="store_true", help="Do not delete scratch directory after benchmark execution.")
    group.add_argument("--no-scratch", action="store_true", help="Do not execute benchmark in scratch directory.")
    return parser


parsers["temporary_workdir_parser"] = ParserEntry(
    _create_temporary_workdir_parser(),
    "\n\nFlags for benchmark suites with temporary working directories:\n"
)


class Vm(object): #pylint: disable=R0922
    """Base class for objects that can run Java VMs."""

    @property
    def bmSuite(self):
        return getattr(self, '_bmSuite', None)

    @bmSuite.setter
    def bmSuite(self, val):
        self._bmSuite = val

    @property
    def command_mapper_hooks(self):
        return getattr(self, '_command_mapper_hooks', None)

    @command_mapper_hooks.setter
    def command_mapper_hooks(self, hooks):
        """
        Registers a list of `hooks` (given as a tuple 'name', 'func', 'suite') to manipulate the command line before its
        execution.
        :param list[tuple] hooks: the list of hooks given as tuples of names and functions
        """
        self._command_mapper_hooks = hooks

    def name(self):
        """Returns the unique name of the Java VM (e.g. server, client, or jvmci)."""
        raise NotImplementedError()

    def config_name(self):
        """Returns the config name for a VM (e.g. graal-core or graal-enterprise)."""
        raise NotImplementedError()

    def extract_vm_info(self, args=None):
        """Extract vm information."""
        pass

    def rules(self, output, benchmarks, bmSuiteArgs):
        """Returns a list of rules required to parse the standard output.

        :param string output: Contents of the standard output.
        :param list benchmarks: List of benchmarks that were run.
        :param list bmSuiteArgs: Arguments to the benchmark suite (after first `--`).
        :return: List of StdOutRule parse rules.
        :rtype: list
        """
        return []

    def runWithSuite(self, bmSuite, cwd, args):
        """Runs the JVM with a particular suite ."""
        self.bmSuite = bmSuite
        t = self.run(cwd, args)
        self.bmSuite = None
        return t

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
        if self._host_vm is not None and self.command_mapper_hooks is not None and self._host_vm.command_mapper_hooks is None:
            self._host_vm.command_mapper_hooks = self.command_mapper_hooks
        return self._host_vm

    def rules(self, output, benchmarks, bmSuiteArgs):
        """Returns a list of rules required to parse the standard output.

        :param string output: Contents of the standard output.
        :param list benchmarks: List of benchmarks that were run.
        :param list bmSuiteArgs: Arguments to the benchmark suite (after first `--`).
        :return: List of StdOutRule parse rules.
        :rtype: list
        """
        return super(GuestVm, self).rules(output, benchmarks, bmSuiteArgs) + self.host_vm().rules(output, benchmarks, bmSuiteArgs)


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
    mx.logv(f"Detected GC is '{gc}'. Heap size : Initial = {initial_heap_size}, Max = {max_heap_size}")
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

    def run_vm(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        """Runs JVM with the specified arguments stdout and stderr, and working dir."""
        raise NotImplementedError()

    def run(self, cwd, args):
        self.extract_vm_info(args)
        out = mx.TeeOutputCapture(mx.OutputCapture())
        args = self.post_process_command_line_args(args)
        mx.log(f"Running {self.name()} with args: {args}")
        code = self.run_vm(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False)
        out = out.underlying.data
        dims = self.dimensions(cwd, args, code, out)
        return code, out, dims


class OutputCapturingJavaVm(OutputCapturingVm): #pylint: disable=R0921
    """A convenience class for running Java VMs."""

    def __init__(self):
        super(OutputCapturingJavaVm, self).__init__()
        self._vm_info = {}
        # prevents an infinite loop when the host-vm is a GraalVm since its `run_java()` function calls `extract_vm_info()`, which calls `run_java()`
        self.currently_extracting_vm_info = False

    def extract_vm_info(self, args=None):
        if args is None:
            # This method will force the caller to pass 'args' in the future to ensure correctness of the output
            mx.log_deprecation("Downstream suite must pass the VM arguments to ensure valid VM info extraction !")
            args = []
        args = self.post_process_command_line_args(args)
        args_str = ' '.join(args)
        if not self.currently_extracting_vm_info and args_str not in self._vm_info:
            self.currently_extracting_vm_info = True
            try:
                vm_info = {}
                hooks = self.command_mapper_hooks
                self.command_mapper_hooks = None
                with mx.DisableJavaDebugging():
                    java_version_out = mx.TeeOutputCapture(mx.OutputCapture())
                    vm_opts = _get_vm_options_for_config_extraction(args)
                    vm_args = vm_opts + ["-version"]
                    mx.logv(f"Extracting vm info by calling : java {' '.join(vm_args)}")
                    code = self.run_java(vm_args, out=java_version_out, err=java_version_out, cwd=".")
                    if code == 0:
                        command_output = java_version_out.underlying.data
                        gc, initial_heap, max_heap = _get_gc_info(command_output)
                        vm_info["platform.gc"] = gc
                        vm_info["platform.initial-heap-size"] = initial_heap
                        vm_info["platform.max-heap-size"] = max_heap

                        version_output = command_output.splitlines()
                        assert len(version_output) >= 3
                        version_start_line = 0
                        for i, line in enumerate(version_output):
                            if " version " in line:
                                version_start_line = i
                                break
                        version_output = version_output[version_start_line:version_start_line+3]
                        jdk_version_number = version_output[0].split("\"")[1]
                        version = mx.VersionSpec(jdk_version_number)
                        jdk_major_version = version.parts[1] if version.parts[0] == 1 else version.parts[0]
                        jdk_version_string = version_output[2]
                        vm_info["platform.jdk-version-number"] = jdk_version_number
                        vm_info["platform.jdk-major-version"] = jdk_major_version
                        vm_info["platform.jdk-version-string"] = jdk_version_string
                        if "jvmci" in jdk_version_string:
                            m = re.search(r'jvmci-(([a-z\d\.\-])*)', jdk_version_string)
                            if m:
                                vm_info["platform.jvmci-version"] = m.group(1)
                        if "GraalVM" in jdk_version_string:
                            # Until 19.3.0 the following format used to exist: 'GraalVM LIBGRAAL_CE_BASH 19.3.0'
                            m = re.search(r'(?P<oracle>Oracle )?GraalVM (?P<edition>CE |EE |LIBGRAAL_CE_BASH | LIBGRAAL_EE_BASH )?(?P<version>(\.?\d+)*)', jdk_version_string)
                            if m:
                                vm_info["platform.graalvm-version-string"] = m.group(0).strip()
                                vm_info["platform.graalvm-version"] = m.group('version').strip()
                                if m.group('edition'):
                                    if "CE" in m.group('edition').upper():
                                        # to accommodate for 'LIBGRAAL_CE_BASH'
                                        vm_info["platform.graalvm-edition"] = "CE"
                                    elif "EE" in m.group('edition').upper():
                                        vm_info["platform.graalvm-edition"] = "EE"
                                elif m.group('oracle'):
                                    vm_info["platform.graalvm-edition"] = "EE"
                                else:
                                    # Edition may be absent from the version string. 'GraalVM 22.0.0-dev' is valid
                                    vm_info["platform.graalvm-edition"] = "unknown"

                        manual_graalvm_edition = mx.get_env("GRAALVM_EDITION", default=None)
                        if manual_graalvm_edition is not None:
                            vm_info["platform.graalvm-edition"] = manual_graalvm_edition
                        manual_graalvm_version = mx.get_env("GRAALVM_VERSION", default=None)
                        if manual_graalvm_version is not None:
                            vm_info["platform.graalvm-version"] = manual_graalvm_version
                    else:
                        mx.log_error(f"VM info extraction failed ! (code={code})")
            finally:
                self.currently_extracting_vm_info = False
                self.command_mapper_hooks = hooks

            self._vm_info[args_str] = vm_info

    def dimensions(self, cwd, args, code, out):
        dims = super(OutputCapturingJavaVm, self).dimensions(cwd, args, code, out)
        vm_info = self._vm_info.get(' '.join(args), None)
        if vm_info is not None:
            dims.update(vm_info)
        return dims

    def generate_java_command(self, args):
        """Provides a way to get the final command line that `run_java` would execute but without actually running it.

        :param args: command line arguments
        :return: the final command as it would be executed by `run_java`
        :rtype: list[str]
        """
        raise NotImplementedError()

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        """Runs JVM with the specified arguments stdout and stderr, and working dir."""
        raise NotImplementedError()

    def home(self):
        """Returns the JAVA_HOME location of that vm"""
        raise mx.get_jdk().home

    def run_vm(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        self.extract_vm_info(args)
        return self.run_java(args=args, out=out, err=err, cwd=cwd, nonZeroIsFatal=nonZeroIsFatal)

    def rules(self, output, benchmarks, bmSuiteArgs):
        rules = []
        if benchmarks and len(benchmarks) == 1:
            # Captures output generated by -XX:+PrintNMethodStatistics
            rules.append(StdOutRule(
                r"Statistics for (?P<methods>[0-9]+) bytecoded nmethods for JVMCI:\n total in heap  = (?P<value>[0-9]+)",
                {
                    "benchmark": benchmarks[0],
                    "vm": "jvmci",
                    "metric.name": "code-size",
                    "metric.value": ("<value>", int),
                    "metric.unit": "B",
                    "metric.type": "numeric",
                    "metric.score-function": "id",
                    "metric.better": "lower",
                    "metric.iteration": 0,
                })
            )

            # Captures output generated by -XX:+CITime
            rules.append(StdOutRule(
                r"C1 {speed: (?P<value>[-+]?\d*\.\d+|\d+) bytes/s;",
                {
                    "benchmark": benchmarks[0],
                    "vm": "jvmci",
                    "metric.name": "baseline-tier-throughput",
                    "metric.value": ("<value>", float),
                    "metric.unit": "B/s",
                    "metric.type": "numeric",
                    "metric.score-function": "id",
                    "metric.better": "higher",
                    "metric.iteration": 0,
                })
            )
            rules.append(StdOutRule(
                r"(C2|JVMCI|JVMCI-native) {speed: (?P<value>[-+]?\d*\.\d+|\d+) bytes/s;",
                {
                    "benchmark": benchmarks[0],
                    "vm": "jvmci",
                    "metric.name": "top-tier-throughput",
                    "metric.value": ("<value>", float),
                    "metric.unit": "B/s",
                    "metric.type": "numeric",
                    "metric.score-function": "id",
                    "metric.better": "higher",
                    "metric.iteration": 0,
                })
            )
        return rules


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

    def generate_java_command(self, args):
        return mx.get_jdk().generate_java_command(self.post_process_command_line_args(args))

    def run_java(self, args, out=None, err=None, cwd=None, nonZeroIsFatal=False):
        return mx.get_jdk().run_java(args, out=out, err=out, cwd=cwd, nonZeroIsFatal=False, command_mapper_hooks=self.command_mapper_hooks)


class DummyJavaVm(OutputCapturingJavaVm):
    """
    Dummy VM to work around: "pylint #111138 disabling R0921 doesn't work"
    https://www.logilab.org/ticket/111138

    Note that the warning R0921 (abstract-class-little-used) has been removed
    from pylint 1.4.3.
    """

def add_java_vm(javavm, suite=None, priority=0):
    """
    Registers a JavaVm.  Higher numbers represent a higher priority.
    """
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


class JMeterBenchmarkSuite(JavaBenchmarkSuite, AveragingBenchmarkMixin):
    """ This class is deprecated and will be removed soon. The new version is now located in mx_sdk_benchmark.py"""
    pass


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

        def _is_forking(args):
            if '-f0' in args:
                return False
            try:
                f_idx = args.index('-f')
                if args[f_idx + 1] == '0':
                    return False
            except (ValueError, IndexError) as _:
                pass
            return True

        vmArgs = self.vmArgs(bmSuiteArgs) + self.extraVmArgs()
        runArgs = self.extraRunArgs() + self.runArgs(bmSuiteArgs)

        if self.profilerNames(bmSuiteArgs) and _is_forking(runArgs):
            mx.warn("Profilers are not currently compatible with the JMH benchmark runner in forked mode.\n" +
                    "Forking can be disable with `-f0` but be aware that this significantly changes the way the benchmark is executed.")

        return vmArgs + self.getJMHEntry(bmSuiteArgs) + ['--jvmArgsPrepend', ' '.join(vmArgs)] + runArgs + (benchmarks if benchmarks else [])

    def successPatterns(self):
        return [
            re.compile(
                r"# Run complete.",
                re.MULTILINE)
        ]

    def benchSuiteName(self, bmSuiteArgs=None):
        return self.name()

    def failurePatterns(self):
        return super(JMHBenchmarkSuiteBase, self).failurePatterns() + [re.compile(r"<failure>")]

    def flakySuccessPatterns(self):
        return []

    def rules(self, out, benchmarks, bmSuiteArgs):
        return [JMHJsonRule(JMHBenchmarkSuiteBase.jmh_result_file, self.benchSuiteName(bmSuiteArgs),
            self.extraBenchProperties(bmSuiteArgs))]

    def jmhArgs(self, bmSuiteArgs):
        vmAndSuiteArgs = self.vmAndRunArgs(bmSuiteArgs)[0]
        args, _ = get_parser(self.jmhParserName()).parse_known_args(vmAndSuiteArgs)
        return args

    def jmhLibrary(self):
        return mx.library("JMH_1_21", fatalIfMissing=True)

    def extraBenchProperties(self, bmSuiteArgs):
        return {}


class JMHJarBasedBenchmarkSuiteBase(JMHBenchmarkSuiteBase):
    """Common superclass for JAR-based JMH suites. Provides utilities to extract the list of benchmarks or filter the
    JMH command line to determine options or benchmark filters."""

    def __init__(self, *args, **kwargs):
        self._extracted_jmh_options = None
        self._extracted_jmh_filters = None
        super(JMHJarBasedBenchmarkSuiteBase, self).__init__(*args, **kwargs)

    def rules(self, out, benchmarks, bmSuiteArgs):
        # Don't try to validate JSON data if we're only listing benchmarks.
        jmhOptions = self._extractJMHOptions(bmSuiteArgs)
        if jmhOptions is not None and '-l' in jmhOptions:
            return []
        else:
            return super(JMHJarBasedBenchmarkSuiteBase, self).rules(out, benchmarks, bmSuiteArgs)

    def successPatterns(self):
        # Don't try to validate benchmark results if we're only listing benchmarks.
        jmhOptions = self._extracted_jmh_options
        if jmhOptions is not None and '-l' in jmhOptions:
            return []
        else:
            return super(JMHJarBasedBenchmarkSuiteBase, self).successPatterns()

    def _extractJMHBenchmarks(self, bmSuiteArgs):
        benchmarks = None
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        out = mx.TeeOutputCapture(mx.OutputCapture())
        # Do not pass any JVM args to extract the benchmark list since they can generate extra output that will be
        # incorrectly interpreted as a benchmark name. We are only interested in the benchmark filters and any
        # exclusions specified with -e flags.
        benchmarkFilter = self.jmhBenchmarkFilter(bmSuiteArgs)
        jmhOptions = self._extractJMHOptions(bmSuiteArgs)
        if '-e' in jmhOptions:
            excludeArgs = ['-e', jmhOptions[jmhOptions.index('-e') + 1]]
        else:
            excludeArgs = []
        jmhListArgs = ["-jar", self.jmhJAR(bmSuiteArgs), "-l"] + benchmarkFilter + excludeArgs
        # we must disable any tracker or hooks that may modify the command and potentially generate extra output
        disable_tracker()
        mx.disable_command_mapper_hooks()
        exit_code = mx.get_jdk().run_java(jmhListArgs, out=out, err=out, cwd=cwd)
        mx.enable_command_mapper_hooks()
        enable_tracker()
        if exit_code != 0:
            raise ValueError("JMH benchmark list extraction failed!")
        benchs = out.underlying.data.splitlines()
        # Discard everything before "Benchmarks:"
        linenumber = -1
        for linenumber in range(len(benchs)):
            if benchs[linenumber].startswith("Benchmarks:"):
                break
        assert linenumber >= 0, "No benchmarks output list found"
        benchnames = benchs[linenumber + 1:]
        assert len(benchnames) >= 1, f"No benchmarks matching {self.jmhBenchmarkFilter(bmSuiteArgs)} and exclusions {excludeArgs} found"
        return benchnames

    def _extractJMHOptionsImpl(self, action, bmSuiteArgs):
        """Run an external Java program to filter the JMH command line from our run arguments. `action` must be either
        '--action=ExtractOptions' to extract options and their arguments, or '--action=ExtractFilters' to extract
        benchmark filters.

        The return value is a list of strings, with options separate from their arguments. Multiple arguments to the
        same option are separated by commas within one string. Flags specified multiple times are grouped by the parser.
        For example, a command line like '-bm avgt -bm thrpt' will be returned as ['-bm', 'avgt,thrpt']."""
        benchmarks = None
        cwd = self.workingDirectory(benchmarks, bmSuiteArgs)
        out = mx.TeeOutputCapture(mx.OutputCapture())
        mx.build(["--no-daemon", "--dependencies", ','.join(self.jmhFilterDeps())])
        print("Filtering JMH command line:")
        jmhOptionArgs = ["-cp", mx.classpath(names=self.jmhFilterDeps()), self.jmhFilterClassName(), action] + self.runArgs(bmSuiteArgs)
        exit_code = mx.get_jdk().run_java(jmhOptionArgs, out=out, err=out, cwd=cwd)
        if exit_code != 0:
            raise ValueError("JMH benchmark option extraction failed")
        return out.underlying.data.splitlines()

    def _extractJMHOptions(self, bmSuiteArgs):
        if self._extracted_jmh_options is None:
            self._extracted_jmh_options = self._extractJMHOptionsImpl("--action=ExtractOptions", bmSuiteArgs)
        return self._extracted_jmh_options

    def _extractJMHFilters(self, bmSuiteArgs):
        if self._extracted_jmh_filters is None:
            self._extracted_jmh_filters = self._extractJMHOptionsImpl("--action=ExtractFilters", bmSuiteArgs)
            # Sanity check: filters should be Java class names or regexes matching Java class names. Don't try to verify
            # regex syntax, but at least ensure there is no initial '-', or '=' or whitespace which would indicate
            # confusion with options.
            for jmhFilter in self._extracted_jmh_filters:
                assert jmhFilter and jmhFilter[0] != '-'
                assert not re.search(r"[=\s]", jmhFilter)
        return self._extracted_jmh_filters

    def jmhFilterDeps(self):
        return ["com.oracle.mxtool.jmh_" + self.jmhVersionString()]

    def jmhFilterClassName(self):
        return self.jmhFilterDeps()[0] + ".FilterJMHFlags"

    def jmhVersionString(self):
        """A string like '1_21' corresponding to the current JMH library's version (in this case, 1.21)."""
        library = self.jmhLibrary()
        version = library.maven["version"]
        return version.replace('.', '_')


def _add_opens_and_exports_from_manifest(jarfile, add_opens=True, add_exports=True):
    vm_args = []
    lines = None
    if os.path.isfile(jarfile):
        archive = zipfile.ZipFile(jarfile, "r")
        if "META-INF/MANIFEST.MF" in archive.namelist():
            manifest = archive.read("META-INF/MANIFEST.MF").decode('utf-8')
            lines = manifest.splitlines()
    else:
        # may happen with exploded jar files
        path = os.path.join(jarfile, "META-INF", "MANIFEST.MF")
        mx.log(path)
        if os.path.exists(path):
            with open(path) as f:
                lines = f.readlines()
    if lines:
        if add_opens:
            add_opens_entries = [line for line in lines if line.strip().startswith("Add-Opens:")]
            if len(add_opens_entries) > 1:
                # We decide to enforce that the manifest contains no duplicate lines. The JVM would be more relaxed
                # in that case and only consider then last Add-Opens line, but since the manifest generation is under
                # our control, it's better to enforce it here.
                raise ValueError(f"Manifest file of {jarfile} contains multiple Add-Opens lines!")
            if add_opens_entries:
                vm_args += [f"--add-opens={package.strip()}=ALL-UNNAMED" for package in add_opens_entries[-1][len("Add-Opens:"):].strip().split(" ")]
        if add_exports:
            # We decide to enforce that the manifest contains no duplicate lines. The JVM would be more relaxed
            # in that case and only consider then last Add-Exports line, but since the manifest generation is under
            # our control, it's better to enforce it here.
            add_exports_entries = [line for line in lines if line.strip().startswith("Add-Exports:")]
            if len(add_exports_entries) > 1:
                raise ValueError(f"Manifest file of {jarfile} contains multiple Add-Exports lines!")
            if add_exports_entries:
                vm_args += [f"--add-exports={package.strip()}=ALL-UNNAMED" for package in add_exports_entries[-1][len("Add-Exports:"):].strip().split(" ")]

    return vm_args


class JMHDistBenchmarkSuite(JMHJarBasedBenchmarkSuiteBase):
    """
    JMH benchmark suite that executes microbenchmark mx distribution.

    It also supports extraction of the `Add-Opens` and `Add-Exports` entries from the manifest and places them on the
    command line. This has the advantage of not relying on the JVM to open/export the relevant packages since it isn't
    sufficient when new JVMs are forked (which is the default and desirable mode of JMH).

    Since manifest entries can be specified in the mx suite distribution definition, one can use this simple approach
    to ensure all desired --add-opens and --add-exports are added to the underlying command line.

    """
    jmh_dist_parser_name = "jmh_dist_benchmark_suite_vm"

    def benchSuiteName(self, bmSuiteArgs=None):
        if self.dist:
            return "jmh-" + self.dist
        if bmSuiteArgs is None:
            bmSuiteArgs = []
        return super(JMHDistBenchmarkSuite, self).benchSuiteName(bmSuiteArgs)

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        if benchmarks is None:
            mx.abort(f"JMH Dist Suite requires a JMH distribution. (try {self.name()}:*)")
        if len(benchmarks) != 1:
            mx.abort(f"JMH Dist Suite runs only a single JMH distribution, got: {benchmarks}")
        self.dist = benchmarks[0]
        mx.log("running " + self.dist)
        return super(JMHDistBenchmarkSuite, self).createCommandLineArgs(None, bmSuiteArgs)

    def extraVmArgs(self):
        assert self.dist
        distribution = mx.distribution(self.dist)
        assert distribution.isJARDistribution()
        jdk = mx.get_jdk(distribution.javaCompliance)
        add_opens_add_extracts = []
        if mx_benchmark_compatibility().jmh_dist_benchmark_extracts_add_opens_from_manifest():
            add_opens_add_extracts = _add_opens_and_exports_from_manifest(distribution.path)
        return mx.get_runtime_jvm_args([self.dist], jdk=jdk) + add_opens_add_extracts

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

    def jmhJAR(self, bmSuiteArgs):
        # self.jmhJar must be set by runAndReturnStdOut
        assert hasattr(self, 'jmhJar') and self.jmhJar is not None
        return self.jmhJar

    def parserNames(self):
        return super(JMHDistBenchmarkSuite, self).parserNames() + [self.jmhParserName()]

    def jmhParserName(self):
        return JMHDistBenchmarkSuite.jmh_dist_parser_name

    def jmhBenchmarkFilter(self, bmSuiteArgs):
        return self._extractJMHFilters(bmSuiteArgs)

    def runAndReturnStdOut(self, benchmarks, bmSuiteArgs):
        run_individually = self.jmhArgs(bmSuiteArgs).jmh_run_individually
        jmhOptions = self._extractJMHOptions(bmSuiteArgs)
        list_only = '-l' in jmhOptions
        if run_individually and not list_only:
            # Extract the list of benchmarks to run and the user's JMH options.
            if len(benchmarks) != 1:
                mx.abort(f"JMH Dist Suite runs only a single JMH distribution, got: {benchmarks}")
            distribution = mx.distribution(benchmarks[0])
            assert distribution.isJARDistribution()
            self.jmhJar = distribution.path
            vmArgs, _ = self.vmAndRunArgs(bmSuiteArgs)
            extracted_jmh_benchmarks = self._extractJMHBenchmarks(bmSuiteArgs)

            partSpecification = self.jmhArgs(bmSuiteArgs).jmh_individual_part
            benchmarks_to_run = self._selectPart(extracted_jmh_benchmarks, partSpecification)
            if benchmarks_to_run != extracted_jmh_benchmarks:
                print(f"Run part {partSpecification}: {len(benchmarks_to_run)} of {len(extracted_jmh_benchmarks)} benchmarks, {benchmarks_to_run[0]} to {benchmarks_to_run[-1]}")

            # Run each benchmark individually. Record outputs and collect the JSON result files' contents.
            allOut = ''
            lastDims = None
            jsons = []
            for benchmark in benchmarks_to_run:
                individualBmArgs = vmArgs + ['--'] + jmhOptions + [benchmark]
                print("Individual JMH benchmark run:", benchmark)
                retcode, out, dims = super(JMHDistBenchmarkSuite, self).runAndReturnStdOut(benchmarks, individualBmArgs)
                if retcode is not None and retcode != 0:
                    mx.abort(f"Execution with args {individualBmArgs} exited with non-zero return code {retcode}.")
                allOut += out
                if lastDims is not None and lastDims != dims:
                    mx.abort(f"Expected equal dims\nlast: {lastDims}\ncurr: {dims}")
                lastDims = dims
                json = open(JMHBenchmarkSuiteBase.jmh_result_file).read().strip()
                assert json[0] == '[' and json[-1] == ']'
                jsons += [json[1:-1]]

            # Combine the collected JSON results into one result file.
            with open(JMHBenchmarkSuiteBase.jmh_result_file, 'w') as result_file:
                result_file.write('[')
                for index, json in enumerate(jsons):
                    result_file.write(json)
                    if index < len(jsons) - 1:
                        result_file.write(',\n')
                result_file.write(']')
            return 0, allOut, lastDims
        else:
            return super(JMHDistBenchmarkSuite, self).runAndReturnStdOut(benchmarks, bmSuiteArgs)

    def _selectPart(self, benchmarks, partSpecification):
        """
        Select part of the benchmark list based on a specification like "3/4", meaning "the third quarter of the list".
        For example, selecting `3/4` from a list `[a, b, c, d, e, f, g, h]` will result in `[e, f]`. Cutting a list into
        parts `1/n` to `n/n` will result in roughly equal-size lists that cover the entire list. For example, selecting
        parts `1/3`, `2/3`, and `3/3` from a list `[a, b, c, d]` will give lists `[a]`, `[b]`, and `[c, d]`.
        """
        try:
            n, m = partSpecification.split('/')
            part = int(n)
            parts = int(m)
        except:
            mx.abort("Benchmark part specification must be of the form n/m")
        if not 1 <= part <= parts:
            mx.abort("Benchmark part specification n/m requires 1 <= n <= m")
        if parts > len(benchmarks):
            mx.abort(f"Can't cut benchmark list of length {len(benchmarks)} into {parts} parts")

        start = (len(benchmarks) // parts) * (part - 1)
        if part < parts:
            end = start + (len(benchmarks) // parts)
        else:
            end = len(benchmarks)
        selected = benchmarks[start:end]

        # Make sure we don't lose elements around the edges.
        if part == 1:
            assert selected[0] == benchmarks[0]
        if part == parts:
            assert selected[-1] == benchmarks[-1]

        return selected

    def extraBenchProperties(self, bmSuiteArgs):
        properties = super(JMHDistBenchmarkSuite, self).extraBenchProperties(bmSuiteArgs)
        run_individually = self.jmhArgs(bmSuiteArgs).jmh_run_individually
        if run_individually:
            properties["mx-individual-run-mode"] = "one-vm-per-benchmark"
        return properties

_jmh_dist_args_parser = ParserEntry(
    ArgumentParser(add_help=False, usage=_mx_benchmark_usage_example + " -- <options> -- ..."),
    "\n\nOptions for JMH dist benchmark suites:\n"
)
_jmh_dist_args_parser.parser.add_argument("--jmh-run-individually", action='store_true')
_jmh_dist_args_parser.parser.add_argument("--jmh-individual-part", default="1/1")

add_parser(JMHDistBenchmarkSuite.jmh_dist_parser_name, _jmh_dist_args_parser)


class JMHRunnerBenchmarkSuite(JMHBenchmarkSuiteBase):
    """JMH benchmark suite that uses jmh-runner to execute projects with JMH benchmarks."""

    def benchmarkList(self, bmSuiteArgs):
        """Return all different JMH versions found."""
        return list(JMHRunnerBenchmarkSuite.get_jmh_projects_dict().keys())

    def createCommandLineArgs(self, benchmarks, bmSuiteArgs):
        if benchmarks is None:
            mx.abort("JMH Suite runs only a single JMH version.")
        if len(benchmarks) != 1:
            mx.abort(f"JMH Suite runs only a single JMH version, got: {benchmarks}")
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


class JMHJarBenchmarkSuite(JMHJarBasedBenchmarkSuiteBase):
    """
    JMH benchmark suite that executes microbenchmarks in a JMH jar.

    This suite relies on the `--jmh-jar` and `--jmh-name` to be set. The former
    specifies the path to the JMH jar files. The later is the name suffix that is use
    for the bench-suite property.
    """
    jmh_jar_parser_name = "jmh_jar_benchmark_suite_vm"

    def __init__(self, *args, **kwargs):
        self._extracted_jmh_benchmarks = None
        super(JMHJarBenchmarkSuite, self).__init__(*args, **kwargs)

    def benchmarkList(self, bmSuiteArgs):
        if self._extracted_jmh_benchmarks is not None:
            return self._extracted_jmh_benchmarks

        self._extracted_jmh_benchmarks = self._extractJMHBenchmarks(bmSuiteArgs)
        return self._extracted_jmh_benchmarks

    def benchSuiteName(self, bmSuiteArgs=None):
        return "jmh-" + self.jmhName(bmSuiteArgs)

    def getJMHEntry(self, bmSuiteArgs):
        return ["-jar", self.jmhJAR(bmSuiteArgs)]

    def parserNames(self):
        return super(JMHJarBenchmarkSuite, self).parserNames() + [self.jmhParserName()]

    def jmhParserName(self):
        return JMHJarBenchmarkSuite.jmh_jar_parser_name

    def jmhName(self, bmSuiteArgs):
        jmh_name = self.jmhArgs(bmSuiteArgs).jmh_name
        if jmh_name is None:
            mx.abort("Please use the --jmh-name benchmark suite argument to set the name of the JMH suite.")
        return jmh_name

    def jmhBenchmarkFilter(self, bmSuiteArgs):
        jmh_benchmarks = self.jmhArgs(bmSuiteArgs).jmh_benchmarks
        if not jmh_benchmarks:
            return []
        mx.log_deprecation("The --jmh-benchmarks flag is deprecated, please list the benchmarks to run as JMH parameters (after the last '--').")
        return jmh_benchmarks.split(',')

    def jmhJAR(self, bmSuiteArgs):
        jmh_jar = self.jmhArgs(bmSuiteArgs).jmh_jar
        if jmh_jar is None:
            mx.abort("Please use the --jmh-jar benchmark suite argument to set the JMH jar file.")
        jmh_jar = os.path.expanduser(jmh_jar)
        if not os.path.exists(jmh_jar):
            mx.abort("The --jmh-jar argument points to a non-existing file: " + jmh_jar)
        return jmh_jar


_jmh_args_parser = ParserEntry(
    ArgumentParser(add_help=False, usage=_mx_benchmark_usage_example + " -- <options> -- ..."),
    "\n\nVM selection flags for JMH benchmark suites:\n"
)
_jmh_args_parser.parser.add_argument("--jmh-jar", default=None)
_jmh_args_parser.parser.add_argument("--jmh-name", default=None)
_jmh_args_parser.parser.add_argument("--jmh-benchmarks", default="")

add_parser(JMHJarBenchmarkSuite.jmh_jar_parser_name, _jmh_args_parser)


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
        mx.logv(f"Could not parse the build number from BUILD_NUMBER. Expected int, instead got: {build_num}")
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
        return f"{base_url}/builds/{build_num}"
    return ""


_use_tracker = True

def enable_tracker():
    global _use_tracker
    _use_tracker = True

def disable_tracker():
    global _use_tracker
    _use_tracker = False

class Tracker(object):
    def __init__(self, bmSuite):
        self.bmSuite = bmSuite

    def map_command(self, cmd):
        raise NotImplementedError()

    def get_rules(self, bmSuiteArgs):
        raise NotImplementedError()

class RssTracker(Tracker):
    def map_command(self, cmd):
        """
        Tracks the max resident memory size used by the process using the 'time' command.

        :param list[str] cmd: the input command to modify
        :return:
        """
        if not _use_tracker:
            return cmd
        if mx.get_os() == "linux":
            prefix = ["time", "-v"]
        elif mx.get_os() == "darwin":
            prefix = ["time", "-l"]
        else:
            mx.log(f"Ignoring the 'rss' tracker since it is not supported on {mx.get_os()}")
            prefix = []
        return prefix + cmd

    def get_rules(self, bmSuiteArgs):
        if mx_benchmark_compatibility().bench_suite_needs_suite_args():
            suite_name = self.bmSuite.benchSuiteName(bmSuiteArgs)
        else:
            suite_name = self.bmSuite.benchSuiteName()
        if mx.get_os() == "linux":
            # Output of 'time -v' on linux contains:
            #        Maximum resident set size (kbytes): 511336
            rules = [
                StdOutRule(
                    r"Maximum resident set size \(kbytes\): (?P<rss>[0-9]+)",
                    {
                        "benchmark": self.bmSuite.currently_running_benchmark(),
                        "bench-suite": suite_name,
                        "config.vm-flags": ' '.join(self.bmSuite.vmArgs(bmSuiteArgs)),
                        "metric.name": "max-rss",
                        "metric.value": ("<rss>", lambda x: int(float(x)/(1024))),
                        "metric.unit": "MB",
                        "metric.type": "numeric",
                        "metric.score-function": "id",
                        "metric.better": "lower",
                        "metric.iteration": 0
                    }
                )
            ]
        elif mx.get_os() == "darwin":
            # Output of 'time -l' on linux contains (size in bytes):
            #  523608064  maximum resident set size
            rules = [
                StdOutRule(
                    r"(?P<rss>[0-9]+)\s+maximum resident set size",
                    {
                        "benchmark": self.bmSuite.currently_running_benchmark(),
                        "bench-suite": suite_name,
                        "config.vm-flags": ' '.join(self.bmSuite.vmArgs(bmSuiteArgs)),
                        "metric.name": "max-rss",
                        "metric.value": ("<rss>", lambda x: int(float(x)/(1024*1024))),
                        "metric.unit": "MB",
                        "metric.type": "numeric",
                        "metric.score-function": "id",
                        "metric.better": "lower",
                        "metric.iteration": 0
                    }
                )
            ]
        else:
            rules = []
        return rules


class PsrecordTracker(Tracker):
    def __init__(self, bmSuite):
        super().__init__(bmSuite)
        self.most_recent_text_output = None

    def map_command(self, cmd):
        """
        Delegates the command execution to 'psrecord' that will also capture memory and CPU consumption of the process.

        :param list[str] cmd: the input command to modify
        """
        if not _use_tracker:
            self.most_recent_text_output = None
            return cmd

        import datetime
        bench_name = self.bmSuite.currently_running_benchmark() if self.bmSuite else "benchmark"
        if self.bmSuite:
            bench_name = f"{self.bmSuite.name()}-{bench_name}"
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        text_output = os.path.join(os.getcwd(), f"ps_{bench_name}_{ts}.txt")
        plot_output = os.path.join(os.getcwd(), f"ps_{bench_name}_{ts}.png")
        if mx.run(["psrecord", "-h"], nonZeroIsFatal=False, out=mx.OutputCapture(), err=mx.OutputCapture()) != 0:
            mx.abort("Memory tracking requires the 'psrecord' dependency. Install it with: 'pip install psrecord'")

        self.most_recent_text_output = text_output
        cmd_string = " ".join(shlex.quote(arg) for arg in cmd)
        return ["psrecord", "--interval", "0.1", "--log", text_output, "--plot", plot_output, "--include-children", cmd_string]

    def get_rules(self, bmSuiteArgs):
        return [PsrecordTracker.PsrecordRule(self, bmSuiteArgs)]

    class PsrecordRule(CSVBaseRule):
        def __init__(self, tracker, bmSuiteArgs, **kwargs):
            replacement = {
                "benchmark": tracker.bmSuite.currently_running_benchmark(),
                "bench-suite": tracker.bmSuite.benchSuiteName(bmSuiteArgs) if mx_benchmark_compatibility().bench_suite_needs_suite_args() else tracker.bmSuite.benchSuiteName(),
                "config.vm-flags": ' '.join(tracker.bmSuite.vmArgs(bmSuiteArgs)),
                "metric.name": ("<metric_name>", str),
                "metric.value": ("<metric_value>", int),
                "metric.unit": "MB",
                "metric.type": "numeric",
                "metric.score-function": "id",
                "metric.better": "lower",
                "metric.iteration": 0
            }
            super().__init__(["elapsed-wall", "cpu%", "rss_mb", "vsz_mb"],
                             replacement, delimiter=' ', skipinitialspace=True, **kwargs)
            self.tracker = tracker

        def getCSVFiles(self, text):
            file = self.tracker.most_recent_text_output
            return [file] if file else []

        def parseResults(self, text):
            rows = super().parseResults(text)
            rows = rows[1:]  # first row contains malformatted (unquoted) headings
            if not rows:
                return []
            values = sorted(float(r["rss_mb"]) for r in rows)

            def pc(k): # k-percentile with linear interpolation between closest ranks
                x = (len(values) - 1) * k / 100
                fr = int(x)
                cl = int(x + 0.5)
                v = values[fr] if fr == cl else values[fr] * (cl - x) + values[cl] * (x - fr)
                return {"metric_name": "rss_p" + str(k), "metric_value": str(int(v))}

            return [pc(100), pc(99), pc(95), pc(90), pc(75), pc(50), pc(25)]


class PsrecordMaxrssTracker(Tracker):
    """Uses both `time` for exact maximum RSS and `psrecord` for percentiles from sampling."""

    def __init__(self, bmSuite):
        super().__init__(bmSuite)
        self.rss = RssTracker(bmSuite)
        self.psrecord = PsrecordTracker(bmSuite)

    def map_command(self, cmd):
        # Note that psrecord tracks the metrics of the `time` tool as well, which adds 1-2M of RSS.
        # Vice versa, `time` would track psrecord's Python interpreter, which adds more than 10M.
        return self.psrecord.map_command(self.rss.map_command(cmd))

    def get_rules(self, bmSuiteArgs):
        return self.rss.get_rules(bmSuiteArgs) + self.psrecord.get_rules(bmSuiteArgs)


_available_trackers = {
    "rss": RssTracker,
    "psrecord": PsrecordTracker,
    "psrecord+maxrss": PsrecordMaxrssTracker,
}


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
                    raise ValueError(f"Cannot handle extra '{kv}'. Extras key-value pairs must contain a single colon.")
                k, v = split_kv
                if not re.match(r"^[\w\d\._-]*$", k):
                    raise ValueError(f"Extra key can only contain numbers, characters, underscores and dashes. Got '{k}'")
                extras[f"extra.{k}"] = v
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
          "bench-suite-version": suite.version(),
          "config.vm-flags": " ".join(suite.vmArgs(bmSuiteArgs)),
          "config.run-flags": " ".join(suite.runArgs(bmSuiteArgs)),
          "config.build-flags": self.buildFlags(),
          "machine.name": self.machineName(mxBenchmarkArgs),
          "machine.node": self.machineNode(mxBenchmarkArgs),
          "machine.ip": self.machineIp(mxBenchmarkArgs),
          "machine.hostname": self.machineHostname(),
          "machine.arch": self.machineArch(),
          "machine.os": self.machineOs(),
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

        if mx.get_env("MACHINE_CONFIG_HASH", default=None):
            standard.update({"machine.config-hash": mx.get_env("MACHINE_CONFIG_HASH")[:7]})

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
            if (ignored and mxsuite.name in ignored) or mxsuite.ignore_suite_commit_info:
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
            mx.abort(f"Cannot find benchmark suite '{suitename}'. Available suites are: {' '.join(bm_suite_valid_keys())}")
        if args.bench_suite_version:
            suite.setDesiredVersion(args.bench_suite_version)
        if not exclude and benchspec == "*":
            return (suite, [[b] for b in suite.completeBenchmarkList(bmSuiteArgs)])
        elif not exclude and benchspec.startswith("*[") and benchspec.endswith("]"):
            all_benchmarks = suite.completeBenchmarkList(bmSuiteArgs)
            requested_benchmarks = [bench.strip() for bench in benchspec[2:-1].split(",")]
            if not set(requested_benchmarks) <= set(all_benchmarks):
                difference = list(set(requested_benchmarks) - set(all_benchmarks))
                mx.abort(f"Benchmarks not supported by the suite: {','.join(difference)}")
            return (suite, [[b] for b in all_benchmarks if b in requested_benchmarks])
        elif benchspec.startswith("r[") and benchspec.endswith("]"):
            all_benchmarks = suite.completeBenchmarkList(bmSuiteArgs)
            # python2 compat: instead of regex.fullmatch, use the end-of-string anchor and regex.match
            regex = re.compile(benchspec[2:-1] + r"\Z")
            requested_benchmarks = set()
            for bench in all_benchmarks:
                if regex.match(bench):
                    requested_benchmarks.add(bench)
            if requested_benchmarks == set():
                mx.warn(f"The pattern '{regex.pattern}' doesn't match any benchmark from the suite '{suitename}'.")
            if exclude:
                requested_benchmarks = set(all_benchmarks) - requested_benchmarks
            return (suite, [[b] for b in requested_benchmarks])
        elif exclude and benchspec.startswith("[") and benchspec.endswith("]"):
            all_benchmarks = suite.completeBenchmarkList(bmSuiteArgs)
            excluded_benchmarks = [bench.strip() for bench in benchspec[1:-1].split(",")]
            if not set(excluded_benchmarks) <= set(all_benchmarks):
                difference = list(set(excluded_benchmarks) - set(all_benchmarks))
                mx.abort(f"Benchmarks not supported by the suite: {','.join(difference)}")
            return (suite, [[b] for b in all_benchmarks if b not in excluded_benchmarks])
        elif benchspec == "":
            return (suite, [None])
        else:
            benchspec = [bench.strip() for bench in benchspec.split(",")]
            all_benchmarks = suite.completeBenchmarkList(bmSuiteArgs)
            for bench in benchspec:
                if not bench in all_benchmarks:
                    mx.abort(f"Cannot find benchmark '{bench}' in suite '{suitename}'. Available benchmarks are {all_benchmarks}")
            if exclude:
                return (suite, [[bench] for bench in all_benchmarks if bench not in benchspec])
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
                    raise ValueError(f"'metric.score-function' multiply factor must be numerical ! Got '{factor}'")
                datapoint["metric.score-value"] = float(metric_value) * factor
            else:
                mx.abort(f"Unknown score function '{function}'.")

    def add_fork_number(self, datapoint, fork_number):
        if 'metric.fork-number' not in datapoint:
            datapoint['metric.fork-number'] = fork_number

    def execute(self, suite, benchnames, mxBenchmarkArgs, bmSuiteArgs, fork_number=0):
        start_time = time.time()
        def postProcess(results):
            processed = []
            dim = self.dimensions(suite, mxBenchmarkArgs, bmSuiteArgs)
            for result in results:
                if not isinstance(result, dict):
                    result = result.__dict__
                data_point = dim.copy()
                data_point.update(result)
                data_point["benchmarking.start-ts"] = int(start_time)
                data_point["benchmarking.end-ts"] = int(time.time())
                self.applyScoreFunction(data_point)
                self.add_fork_number(data_point, fork_number)
                processed.append(data_point)
            return processed

        suite._currently_running_benchmark = ''.join(benchnames) if benchnames else ""
        results = suite.run(benchnames, bmSuiteArgs)
        processedResults = postProcess(results)
        suite._currently_running_benchmark = None
        return processedResults

    def benchmark(self, mxBenchmarkArgs, bmSuiteArgs, returnSuiteAndResults=False):
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
            "--fail-fast", action="store_true", default=None,
            help="Abort as soon as an error is caught instead of trying to execute all benchmarks.")
        parser.add_argument(
            "--results-file",
            default="bench-results.json",
            help="Path to JSON output file with benchmark results.")
        parser.add_argument(
            "--bench-suite-version", default=None, help="Desired version of the benchmark suite to execute.")
        parser.add_argument(
            "--tracker", default='rss', help="Enable extra trackers like 'rss' or 'psrecord'. If not set, 'rss' is used.")
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
            "--hwloc-bind", type=str, default=None, help="A space-separated string of one or more arguments that should passed to 'hwloc-bind'.")
        parser.add_argument(
            "--deferred-tty", action="store_true", default=None,
            help="Print the output of the benchmark in one block at the end.")
        parser.add_argument(
            "-h", "--help", action="store_true", default=None,
            help="Show usage information.")
        mxBenchmarkArgs = parser.parse_args(mxBenchmarkArgs)

        out = None
        err = None
        if mxBenchmarkArgs.deferred_tty:
            out = OutputDump(sys.stdout)
            err = OutputDump(sys.stderr)

        with TTYCapturing(out=out, err=err):
            suite = None
            if mxBenchmarkArgs.benchmark:
                # The suite will read the benchmark specifier,
                # and therewith produce a list of benchmark sets to run in separate forks.
                # Later, the harness passes each set of benchmarks from this list to the suite separately.
                suite, benchNamesList = self.getSuiteAndBenchNames(mxBenchmarkArgs, bmSuiteArgs)


            if mxBenchmarkArgs.hwloc_bind:
                suite.register_command_mapper_hook("hwloc-bind", make_hwloc_bind(mxBenchmarkArgs.hwloc_bind))

            if mxBenchmarkArgs.tracker == 'none':
                mxBenchmarkArgs.tracker = None

            if mxBenchmarkArgs.tracker:
                if mxBenchmarkArgs.tracker not in _available_trackers:
                    raise ValueError(f"Unknown tracker '{mxBenchmarkArgs.tracker}'. Use one of: {', '.join(_available_trackers.keys())}")
                if suite:
                    mx.log(f"Registering tracker: {mxBenchmarkArgs.tracker}")
                    suite.register_tracker(mxBenchmarkArgs.tracker, _available_trackers[mxBenchmarkArgs.tracker])

            if mxBenchmarkArgs.list:
                if mxBenchmarkArgs.benchmark and suite:
                    print(f"The following benchmarks are available in suite {suite.name()}:\n")
                    for name in suite.benchmarkList(bmSuiteArgs):
                        print("  " + name)
                    if isinstance(suite, VmBenchmarkSuite):
                        print(f"\n{suite.get_vm_registry().get_available_vm_configs_help()}")
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
                        print(f"\nThe following {vmreg.vm_type_name} benchmark suites are available:\n")
                        for name in bm_suite_names:
                            print("  " + name)
                        print(f"\n{vmreg.get_available_vm_configs_help()}")
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
                    print(f"\n{vmreg.get_available_vm_configs_help()}")
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
            failed_benchmarks = []
            try:
                suite.before(bmSuiteArgs)
                skipped_benchmark_forks = []
                ignored_benchmarks = []
                for benchnames in benchNamesList:
                    suite.validateEnvironment()
                    fork_count = 1
                    if fork_count_spec and benchnames and len(benchnames) == 1:
                        fork_count = fork_count_spec.get(f"{suite.name()}:{benchnames[0]}")
                        if fork_count is None and benchnames[0] in fork_count_spec:
                            mx.log(f"[FORKS] Found a fallback entry '{benchnames[0]}' in the fork counts file. Please use the full benchmark name instead: '{suite.name()}:{benchnames[0]}'")
                            fork_count = fork_count_spec.get(benchnames[0])
                    elif fork_count_spec and len(suite.benchmarkList(bmSuiteArgs)) == 1:
                        # single benchmark suites executed by providing the suite name only or a wildcard
                        fork_count = fork_count_spec.get(suite.name(), fork_count_spec.get(f"{suite.name()}:*"))
                    elif fork_count_spec:
                        mx.abort("The 'fork count' feature is only supported when the suite runs each benchmark in a fresh VM.\nYou might want to use: mx benchmark <options> '<benchmark-suite>:*'")
                    if fork_count_spec and fork_count is None:
                        mx.log(f"[FORKS] Skipping benchmark '{suite.name()}:{benchnames[0]}' since there is no value for it in the fork count file.")
                        skipped_benchmark_forks.append(f"{suite.name()}:{benchnames[0]}")
                    else:
                        for fork_num in range(0, fork_count):
                            if fork_count_spec:
                                mx.log(f"Execution of fork {fork_num + 1}/{fork_count}")
                            try:
                                if benchnames and len(benchnames) > 0 and not benchnames[0] in suite.benchmarkList(bmSuiteArgs) and benchnames[0] in suite.completeBenchmarkList(bmSuiteArgs):
                                    mx.log(f"Skipping benchmark '{suite.name()}:{benchnames[0]}' since it isn't supported on the current platform/configuration.")
                                    ignored_benchmarks.append(f"{suite.name()}:{benchnames[0]}")
                                else:
                                    expandedBmSuiteArgs = suite.expandBmSuiteArgs(benchnames, bmSuiteArgs)
                                    for variant_num, suiteArgs in enumerate(expandedBmSuiteArgs):
                                        mx.log(f"Execution of variant {variant_num + 1}/{len(expandedBmSuiteArgs)} with suite args: {suiteArgs}")
                                        results.extend(self.execute(suite, benchnames, mxBenchmarkArgs, suiteArgs, fork_number=fork_num))
                            except (BenchmarkFailureError, RuntimeError):
                                failures_seen = True
                                if benchnames and len(benchnames) > 0:
                                    failed_benchmarks.append(f"{suite.name()}:{benchnames[0]}")
                                else:
                                    failed_benchmarks.append(f"{suite.name()}")
                                mx.log(traceback.format_exc())
                                if mxBenchmarkArgs.fail_fast:
                                    mx.abort("Aborting execution since a failure happened and --fail-fast is enabled")
                nl_tab = '\n\t'
                if ignored_benchmarks:
                    mx.log(f"Benchmarks ignored since they aren't supported on the current platform/configuration:{nl_tab}{nl_tab.join(ignored_benchmarks)}")
                if skipped_benchmark_forks:
                    mx.log(f"[FORKS] Benchmarks skipped since they have no entry in the fork counts file:{nl_tab}{nl_tab.join(skipped_benchmark_forks)}")
            finally:
                try:
                    suite.after(bmSuiteArgs)
                except RuntimeError:
                    failures_seen = True
                    mx.log(traceback.format_exc())

            if not returnSuiteAndResults:
                suite.dump_results_file(mxBenchmarkArgs.results_file, results)
            else:
                mx.log("Skipping benchmark results dumping since they're programmatically returned")

            exit_code = 0
            if failures_seen:
                mx.log_error(f"Failures happened during benchmark(s) execution !"
                             f"The following benchmarks failed:{nl_tab}{nl_tab.join(failed_benchmarks)}")
                exit_code = 1

            if returnSuiteAndResults:
                return exit_code, suite, results
            else:
                return exit_code

def make_hwloc_bind(hwloc_bind_args):
    if mx.run(["hwloc-bind", "--version"], nonZeroIsFatal=False, out=mx.OutputCapture(), err=mx.OutputCapture()) != 0:
        mx.abort("'hwloc-bind' is not on the path. Please install it for your operating system or remove the '--hwloc-bind' argument.")

    def hwloc_bind(cmd, bmSuite):
        return ["hwloc-bind"] + hwloc_bind_args.split() + cmd

    return hwloc_bind

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


def benchmark(args, returnSuiteAndResults=False):
    """Run benchmark suite with given name.

    :Example:

        mx benchmark bmSuiteName[:benchName] [mxBenchmarkArgs] -- [vmArgs] -- [bmSuiteArgs]
        mx benchmark --help

    :param list args:
        List of arguments (see below).

        `bmSuiteName`: Benchmark suite name (e.g. `dacapo`, `renaissance`, `octane`, ...).
        `benchName`: Name of particular benchmark within the benchmark suite
            (e.g. `raytrace`, `deltablue`, `avrora`, ...), or a wildcard (`*`) indicating that
            all the benchmarks need to be executed as separate runs. If omitted, all the
            benchmarks must be executed as part of one run. If `benchName` starts with
            `~`, then all the specified benchmarks are excluded and the unspecified
            benchmarks are executed as part of one run.
            If a wildcard with a `*[bench1,bench2,...]` list is specified,
            then only the subset of the benchmarks from the list is run.
            The syntax `~[bench1,bench2,...]` is equivalent to `~bench1,bench2`.
        `mxBenchmarkArgs`: Optional arguments to the `mx benchmark` command.

            --results-file: Target path where the results will be stored (default: bench-results.json).
            --machine-name: Abstract name of a machine with specific capabilities
                            (e.g. `x52`).

    Note that arguments to `mx benchmark` are separated with double dashes (`--`).
    Everything before the first `--` is passed to the `mx benchmark` command directly.
    Arguments after the first `--` are used to configure the underlying VM, so they can be JVM
    options for instance. The last set of parameters are parameters that are passed
    directly to the benchmark suite.

    Examples:
        mx benchmark dacapo:fop
        mx benchmark dacapo:avrora -- -- -n 3
        mx benchmark renaissance:* -- -XX:PrintCompilation=true --
        mx benchmark octane:richards -p ./results.json -- -XX:+PrintGC -- --iters=10
        mx benchmark dacapo:* --results-file ./results.json --
    """
    mxBenchmarkArgs, bmSuiteArgs = splitArgs(args, "--")
    return _benchmark_executor.benchmark(mxBenchmarkArgs, bmSuiteArgs, returnSuiteAndResults=returnSuiteAndResults)

class OutputDump:
    def __init__(self, out):
        self.out = out
    def __call__(self, data):
        self.out.write(data)

class TTYCapturing(object):
    def __init__(self, out=None, err=None):
        self._out = out
        self._err = err
        self._stdout = None
        self._stderr = None
        if (out is not None and not callable(out)) or (err is not None and not callable(err)):
            mx.abort("'out' and 'err' must be callable to append content. Consider using mx.TeeOutputCapture()")

    def __enter__(self):
        from io import StringIO

        if self._out is not None:
            self._stdout = sys.stdout
            sys.stdout = self._stringio_stdout = StringIO()
        if self._err is not None:
            self._stderr = sys.stderr
            sys.stderr = self._stringio_stderr = StringIO()
        return self

    def __exit__(self, *args):
        if self._out is not None:
            sys.stdout = self._stdout
        if self._err is not None:
            sys.stderr = self._stderr
        if self._out:
            self._out(self._stringio_stdout.getvalue())
        if self._err:
            self._err(self._stringio_stderr.getvalue())


def gate_mx_benchmark(args, out=None, err=None, nonZeroIsFatal=True):
    if (out is not None and not callable(out)) or (err is not None and not callable(err)):
        mx.abort("'out' and 'err' must be callable to append content. Consider using mx.TeeOutputCapture()")
    opts_and_args = args
    if nonZeroIsFatal and "--fail-fast" not in opts_and_args:
        opts_and_args = ["--fail-fast"] + opts_and_args
    with TTYCapturing(out=out, err=err):
        exit_code, suite, results = benchmark(opts_and_args, returnSuiteAndResults=True)
    if exit_code != 0 and nonZeroIsFatal is True:
        mx.abort(f"Benchmark gate failed with args: {opts_and_args}")
    return exit_code, suite, results
