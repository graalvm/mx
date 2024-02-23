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
    parser = argparse.ArgumentParser(
        prog="ps_poller",
        description="Run target_cmd and periodically poll it for RSS using ps",
        usage="ps_poller [OPTIONS] <target_cmd>",
        epilog="The target_cmd process is ran in a new session, and the RSS data of every process in that session is summed up for each poll",
    )

    parser.add_argument("-f", "--output-file", help="File to which to write the polled RSS data (in KB)")
    parser.add_argument(
        "-i", "--poll-interval", type=float, help="Interval between subsequent polling, in seconds", default=0.1
    )
    parser.add_argument("target_cmd", nargs=argparse.REMAINDER, help="Command to run and poll for RSS data")

    args = parser.parse_args()

    output_file = args.output_file
    if output_file is None:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_file = os.path.join(os.getcwd(), f"ps_poller_rss_samples_{ts}.txt")

    return output_file, args.poll_interval, args.target_cmd


def _start_target_process(target_cmd):
    print(f"Starting and attaching to command: \"{' '.join(target_cmd)}\"")
    return subprocess.Popen(target_cmd, start_new_session=True)


def _poll_session(sid, out_file):
    # Get RSS for every process in session
    args = ["ps", "-g", str(sid), "-o", "rss"]
    try:
        ps_proc = subprocess.Popen(args, stdout=out_file)
        ps_return_code = ps_proc.wait()
        if ps_return_code != 0:
            print(f"Command {ps_proc.args} failed with return code {ps_return_code}!")
        return ps_return_code
    except:
        print(f"An exception occurred when trying to start subprocess with {args}")
        return 1


def main(args):
    output_file, poll_interval, target_cmd = _parse_args(args)

    with open(output_file, "w") as f:
        target_proc = _start_target_process(target_cmd)
        target_pid = target_proc.pid

        start_time = time.time()
        target_status = target_proc.poll()
        poll_return_code = 0
        while target_status is None and poll_return_code == 0:  # target process not terminated
            time.sleep(poll_interval)
            poll_return_code = _poll_session(target_pid, f)
            target_status = target_proc.poll()
        end_time = time.time()

        if poll_return_code != 0:
            f.write("FAILED")  # Communicate to tracker that the RSS polling was unsuccessful
            print(
                "Polling for RSS failed! Any samples gathered until this moment will be ignored. Waiting for the target process without RSS polling..."
            )
            target_status = target_proc.wait()
        else:
            print(f"Rss samples saved in file: {output_file}")
            print(f"Elapsed time: {end_time - start_time:.2f}s")

    print(f"Target process return code: {target_status}")
    return target_status  # Propagate target process exit code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
