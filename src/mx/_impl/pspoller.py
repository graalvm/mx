# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
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

import argparse
import subprocess
import sys
import time

def parse_args(args):
    parser = argparse.ArgumentParser(prog="pspoller", description="Run bench_cmd and periodically poll it for RSS using ps", usage="pspoller <output_file_name> <poll_interval> bench_cmd", epilog="The bench_cmd process is ran in a new session, and the RSS data of every process in that session is summed up for each poll")

    parser.add_argument("output_file_name", help="File to which to write the polled RSS data (in KB)")
    parser.add_argument("poll_interval", type=float, help="Interval between subsequent polling, in seconds")
    parser.add_argument("bench_cmd", nargs=argparse.REMAINDER, help="Command to run")

    args = parser.parse_args()
    return args.output_file_name, args.poll_interval, args.bench_cmd


def start_bench(cmd):
    print("Starting and attaching to command: \"{}\"".format(" ".join(cmd)))
    return subprocess.Popen(cmd, start_new_session=True)

def poll_session(sid, out_file):
    # Get RSS for every process with sid, and then calculate sum
    ps_proc = subprocess.Popen(["ps", "-g", str(sid), "-o", "rss="], stdout=subprocess.PIPE) # gets rss of every process in session
    paste_proc = subprocess.Popen(["paste", "-sd+"], stdin=ps_proc.stdout, stdout=subprocess.PIPE) # constructs <rssp1>+<rssp2>+...+<rsspN> string
    bc_proc = subprocess.Popen(["bc"], stdin=paste_proc.stdout, stdout=out_file) # calculates the sum string

def main(args):
    output_file_name, poll_interval, bench_cmd = parse_args(args)

    with open(output_file_name, "w") as f:
        bench_proc = start_bench(bench_cmd)
        bench_pid = bench_proc.pid

        start_time = time.time()
        bench_status = bench_proc.poll()
        while bench_status == None: # bench process not terminated
            time.sleep(poll_interval)
            poll_session(bench_pid, f)
            bench_status = bench_proc.poll()
        end_time = time.time()

    print("Final bench status: {}".format(bench_status))
    print("Elapsed time: {:.2f}s".format(end_time - start_time))
    return bench_status # Propagate bench process exit code

if __name__ == '__main__':
    sys.exit(main(sys.argv))
