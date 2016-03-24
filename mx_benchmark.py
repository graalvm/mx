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

import mx

from argparse import ArgumentParser


_benchmark_suites = {}


class BenchmarkSuite(object):
    def name():
        """Returns the name of the suite.

        :returns: Name of the suite.
        :rtype: basestring
        """
        raise NotImplementedError()

    def benchmarks():
        """Returns the list of the benchmarks provided by this suite.

        :returns: List of benchmarks.
        :rtype: list of strings
        """
        raise NotImplementedError()

    def extraDimensions(benchmark, vmargs, runargs):
        """Returns dictionary of extra dimensions for the given benchmark and arguments.

        :param benchmark: Name of the benchmark.
        :type benchmark: string
        :param vmargs: List of VM arguments.
        :type vmargs: list of strings
        :param runargs: List of benchmark arguments.
        :type runargs: list of strings
        :returns: Dictionary of field-name/value pairs.
        :rtype: dict[basestring, T]
        """
        raise NotImplementedError()

    def run(benchmarks, vmargs, runargs):
        """Runs the specified benchmarks with the given arguments.

        :param benchmarks: List of benchmark names.
        :type benchmark: list of strings
        :param vmargs: List of VM arguments.
        :type vmargs: list of strings
        :param runargs: List of benchmark arguments.
        :type runargs: list of strings
        :returns: An object that can be converted into JSON and is merged with the root.
        :rtype: object
        """
        raise NotImplementedError()


def add_benchmark_suite(suite):
    if suite.name() in _benchmark_suites:
        raise RuntimeError("Benchmark {0} already exists".format(suite.name()))
    _benchmark_suites[suite.name()] = suite


def benchmark(args):

