from os.path import dirname, realpath, sep, pardir
import sys
import json

dir = dirname(realpath(__file__))
sys.path.append(dir + sep + "..")

import mx
import mx_benchmark
from mx_benchmark import benchmark

# setup the primary suite
_suite = mx.Suite(mxDir=dir + sep + 'mx.benchmarks', primary=True, internal=True, importing_suite=None, load=False, vc=None, vc_dir='.')
mx._primary_suite_init(_suite)

# Ensure attribute existence for test
#
# mx_benchmark calls `mx.cpu_count`, which in turn calls `_opts.cpu_count`.
# However, the attribute is only set from the `mx` entry point by the
# argument parser. In unit tests, the attribute is thus missing.
setattr(mx._opts, "cpu_count", None)

_test_vm_registry = mx_benchmark.VmRegistry('TestBench', 'testbench-vm')

benchmark_list = ["a", "b", "123", "hello-world", "A", "X-Y"]

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
        return [
            { "benchmark" : benchmark, "arguments": bmSuiteArgs }
            for benchmark in benchmarks
        ]

def check(command, included, excluded):
    print("mx benchmark " + command)

    benchmark([command, '--results-file', 'results.json'])

    f = open('results.json')
    results = json.load(f)
    f.close()

    for result in results['queries']:
        benchmarks = result["benchmark"]

        if not benchmarks in included:
            mx.abort("The test " + benchmarks + " is not in the specified list: " + str(included))

        included.remove(benchmarks)

        if benchmarks in excluded:
            mx.abort("The test " + benchmarks + " is in the excluded list: " + str(excluded))

    if included: # not empty
        mx.abort("The expected tests are not executed: " + str(included))

def checkInclded(command, included):
    check(command, included, set(benchmark_list) - set(included))

def checkExcluded(command, excluded):
    check(command, set(benchmark_list) - set(excluded), excluded)

mx_benchmark.add_bm_suite(TestBenchBenchmarkSuite())

checkInclded("benchSuite:a", ["a"])
checkInclded("benchSuite:*[a,X-Y,123]", ["a", "X-Y", "123"]) # no space allowed around comma
checkExcluded("benchSuite:*", [])
checkExcluded("benchSuite:~a", ["a"])
checkExcluded("benchSuite:~a,b", ["a", "b"])
checkExcluded("benchSuite:~[a,b]", ["a", "b"]) # no space allowed around comma

# TODO: check exceptional cases
#
# - invalid suite name, benchmark name
# - invalid syntax
#
# It requires code refactoring as the code calls `abort` to terminate the process.
