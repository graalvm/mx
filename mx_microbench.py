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

_microbench_executor = None

def set_microbenchmark_executor(ex):
    global _microbench_executor
    assert _microbench_executor is None, 'cannot override microbenchmark executor twice'
    _microbench_executor = ex


def get_microbenchmark_executor():
    if not _microbench_executor:
        set_microbenchmark_executor(MicrobenchExecutor())
    return _microbench_executor

class MicrobenchExecutor(object):

    def microbench(self, args):
        """run JMH microbenchmark projects"""
        parser = ArgumentParser(prog='mx microbench', description=microbench.__doc__,
                                usage="%(prog)s [command options|VM options] [-- [JMH options]]")
        parser.add_argument('--jar', help='Explicitly specify micro-benchmark location')
        self.add_arguments(parser)

        known_args, args = parser.parse_known_args(args)

        vmArgs, jmhArgs = mx.extract_VM_args(args, useDoubleDash=True)
        vmArgs = self.parseVmArgs(vmArgs)

        # look for -f in JMH arguments
        forking = True
        for i in range(len(jmhArgs)):
            arg = jmhArgs[i]
            if arg.startswith('-f'):
                if arg == '-f' and (i+1) < len(jmhArgs):
                    arg += jmhArgs[i+1]
                try:
                    if int(arg[2:]) == 0:
                        forking = False
                except ValueError:
                    pass

        if known_args.jar:
            # use the specified jar
            args = ['-jar', known_args.jar]
            if not forking:
                args += vmArgs
        else:
            # find all projects with a direct JMH dependency
            jmhProjects = []
            for p in mx.projects_opt_limit_to_suites():
                if 'JMH' in [x.name for x in p.deps]:
                    jmhProjects.append(p.name)
            cp = mx.classpath(jmhProjects)

            # execute JMH runner
            args = ['-cp', cp]
            if not forking:
                args += vmArgs
            args += ['org.openjdk.jmh.Main']

        if forking:
            def quoteSpace(s):
                if " " in s:
                    return '"' + s + '"'
                return s

            forkedVmArgs = map(quoteSpace, self.parseForkedVmArgs(vmArgs))
            args += ['--jvmArgsPrepend', ' '.join(forkedVmArgs)]
        self.run_java(args + jmhArgs)

    def add_arguments(self, parser):
        pass

    def run_java(self, args):
        mx.run_java(args)

    def parseVmArgs(self, vmArgs):
        return vmArgs

    def parseForkedVmArgs(self, vmArgs):
        return vmArgs

def microbench(args):
    get_microbenchmark_executor().microbench(args)
