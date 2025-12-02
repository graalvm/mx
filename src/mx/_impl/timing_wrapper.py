#!/usr/bin/env python3
#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2025, 2025, Oracle and/or its affiliates. All rights reserved.
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

"""
Simple timing wrapper that measures wall-clock time with high precision.
Usage: python timing_wrapper.py <command> [args...]
"""
import sys
import subprocess
import time


def main():
    if len(sys.argv) < 2:
        print("Usage: python timing_wrapper.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1:]

    start_time = time.perf_counter()

    try:
        result = subprocess.run(cmd, check=False)
        elapsed = time.perf_counter() - start_time

        print(f"Wall-clock time: {elapsed:.6f} sec", file=sys.stderr)
        sys.exit(result.returncode)

    except KeyboardInterrupt:
        elapsed = time.perf_counter() - start_time
        print(f"\nWall-clock time (interrupted): {elapsed:.6f} sec", file=sys.stderr)
        sys.exit(1)

    except OSError as e:
        elapsed = time.perf_counter() - start_time
        print(f"Error running command: {e}", file=sys.stderr)
        print(f"Wall-clock time (error): {elapsed:.6f} sec", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
