from os.path import dirname, realpath, sep
import sys

file_dir = dirname(realpath(__file__))
sys.path.append(file_dir + sep + "..")

import mx
import mx_benchmark
from mx_benchmark import gate_mx_benchmark

# setup the primary suite
_suite = mx.Suite(mxDir=file_dir + sep + 'mx.benchmarks', primary=True, internal=True, importing_suite=None, load=False, vc=None, vc_dir='.')
mx._primary_suite_init(_suite)

# Ensure attribute existence for test
#
# mx_benchmark calls `mx.cpu_count`, which in turn calls `_opts.cpu_count`.
# However, the attribute is only set from the `mx` entry point by the
# argument parser. In unit tests, the attribute is thus missing.
setattr(mx._opts, "cpu_count", None)

_test_vm_registry = mx_benchmark.VmRegistry('TestBench', 'testbench-vm')

benchmark_list = ["a", "b", "bbb", "123", "hello-world", "A", "X-Y", "meta, tests"]

class TestBenchBenchmarkSuite(mx_benchmark.VmBenchmarkSuite):
    def group(self):
        return "mx"

    def subgroup(self):
        return "benchmarks"

    def name(self):
        return "benchSuite"

    def benchmarkList(self, bmSuiteArgs):
        return benchmark_list

    def get_vm_registry(self):
        return _test_vm_registry

    def run(self, benchmarks, bmSuiteArgs):
        return [{"benchmark": benchmark, "arguments": bmSuiteArgs} for benchmark in benchmarks]

def check(command, included, excluded):
    mx.log("mx benchmark " + command)

    exit_code, _, results = gate_mx_benchmark([command, '--tracker', 'none'], nonZeroIsFatal=False)

    if exit_code != 0:
        mx.abort("{} exit code was {}".format(command, exit_code))

    executed_benchmarks = set([point["benchmark"] for point in results])

    for test_bench in included:
        if test_bench not in executed_benchmarks:
            mx.abort("The test " + test_bench + " is not in the specified list: " + str(included))

    for executed_bench in executed_benchmarks:
        if executed_bench in excluded:
            mx.abort("The test " + executed_bench + " is in excluded list: " + str(excluded))


def checkIncluded(command, included):
    check(command, included, set(benchmark_list) - set(included))


def checkExcluded(command, excluded):
    check(command, set(benchmark_list) - set(excluded), excluded)


mx_benchmark.add_bm_suite(TestBenchBenchmarkSuite())

checkIncluded("benchSuite:a", ["a"])
checkIncluded("benchSuite:*[a,X-Y,123]", ["a", "X-Y", "123"])
checkIncluded("benchSuite:*[a , X-Y , 123]", ["a", "X-Y", "123"]) # space allowed around comma
checkIncluded("benchSuite:r[[ah].*]", ["a", "hello-world"])
checkIncluded("benchSuite:r[b]", ["b"]) # does not contain bbb, since we use fullmatch
checkIncluded("benchSuite:r[.*, .*]", ["meta, tests"]) # comma and space are interpreted correctly
checkExcluded("benchSuite:*", [])
checkExcluded("benchSuite:~a", ["a"])
checkExcluded("benchSuite:~a,b", ["a", "b"])
checkExcluded("benchSuite:~a , b", ["a", "b"])   # space allowed around comma
checkExcluded("benchSuite:~[a,b]", ["a", "b"])
checkExcluded("benchSuite:~[a , b]", ["a", "b"]) # space allowed around comma
checkExcluded("benchSuite:~r[[ah].*]", ["a", "hello-world"])
checkExcluded("benchSuite:~r[.*, .*]", ["meta, tests"])  # comma and space are interpreted correctly

# TODO: check exceptional cases
#
# - invalid suite name, benchmark name
# - invalid syntax
#
# It requires code refactoring as the code calls `abort` to terminate the process.
