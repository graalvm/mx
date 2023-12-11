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
import datetime
import os
import subprocess
import sys
import time

def _parse_args(args):
    parser = argparse.ArgumentParser(prog="ps_poller", description="Run target_cmd and periodically poll it for RSS using ps", usage="ps_poller [OPTIONS] <target_cmd>", epilog="The target_cmd process is ran in a new session, and the RSS data of every process in that session is summed up for each poll")

    parser.add_argument("-f", "--output-file", help="File to which to write the polled RSS data (in KB)")
    parser.add_argument("-i", "--poll-interval", type=float, help="Interval between subsequent polling, in seconds", default=0.1)
    parser.add_argument("target_cmd", nargs=argparse.REMAINDER, help="Command to run and poll for RSS data")

    args = parser.parse_args()

    output_file = args.output_file
    if output_file == None:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_file = os.path.join(os.getcwd(), f"ps_poller_rss_samples_{ts}.txt")

    return output_file, args.poll_interval, args.target_cmd


def _start_target_process(target_cmd):
    print(f"Starting and attaching to command: \"{' '.join(target_cmd)}\"")
    return subprocess.Popen(target_cmd, start_new_session=True)

def _poll_session(sid, out_file):
    # Get RSS for every process with sid, and then calculate sum
    ps_proc = subprocess.Popen(["ps", "-g", str(sid), "-o", "rss="], stdout=subprocess.PIPE) # gets rss of every process in session
    paste_proc = subprocess.Popen(["paste", "-sd+"], stdin=ps_proc.stdout, stdout=subprocess.PIPE) # constructs <rssp1>+<rssp2>+...+<rsspN> string
    bc_proc = subprocess.Popen(["bc"], stdin=paste_proc.stdout, stdout=out_file) # calculates the sum string

def main(args):
    output_file, poll_interval, target_cmd = _parse_args(args)

    with open(output_file, "w") as f:
        target_proc = _start_target_process(target_cmd)
        target_pid = target_proc.pid

        start_time = time.time()
        target_status = target_proc.poll()
        while target_status == None: # target process not terminated
            time.sleep(poll_interval)
            _poll_session(target_pid, f)
            target_status = target_proc.poll()
        end_time = time.time()

    print(f"Target process return code: {target_status}")
    print(f"Rss samples saved in file: {output_file}")
    print(f"Elapsed time: {end_time - start_time:.2f}s")
    return target_status # Propagate target process exit code

if __name__ == '__main__':
    sys.exit(main(sys.argv))
