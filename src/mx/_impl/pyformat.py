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
from __future__ import annotations

import argparse
import shutil

from . import mx


def find_black() -> str | None:
    return shutil.which("black")


@mx.no_suite_discovery
def pyformat(arg_list: [str]):
    parser = argparse.ArgumentParser(prog="mx pyformat", description="Format python code using the black formatter")
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Do not write files to disk. Will abort if any files have formatting errors",
    )
    parser.add_argument(
        "source_files",
        metavar="FILE",
        nargs="*",
        help="Source files to format (formats the entire primary suite by default)",
    )
    args = parser.parse_args(arg_list)

    black_exe = find_black()

    if not black_exe:
        mx.log_error("Could not find 'black' executable for formatting")
        return 1

    mx.logv(f"Using black executable at {black_exe}")

    source_files: [str] = args.source_files

    if not source_files:
        # By default, we just pass the location of the primary suite and let black do the file discovery
        # Exclude rules can be added to pyproject.toml
        source_files = [mx.primary_suite().dir]

    black_args: [str] = []

    if args.dry_run:
        black_args += ["--check", "--diff", "--color"]

    # Propagate mx verbosity to the formatter
    if mx._opts.verbose:
        black_args += ["--verbose"]

    mx.run([black_exe] + black_args + ["--"] + source_files)

    return 0
