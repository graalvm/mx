#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2024, Oracle and/or its affiliates. All rights reserved.
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
#
import os
import sys
import tempfile
import argparse
import textwrap

from . import mx


@mx.suite_context_free
def mx_sync_common_ci(args):
    common_json_url = "https://raw.githubusercontent.com/oracle/graal/master/common.json"
    common_jsonnet_url = "https://raw.githubusercontent.com/oracle/graal/master/ci/common.jsonnet"
    question = f"Do you want replace common.json with {common_json_url} and replace ci/common.jsonnet with {common_jsonnet_url}"
    if mx.ask_yes_no(question):
        common_json_path = os.path.join(mx._mx_suite.dir, "common.json")
        mx.download(common_json_path, [common_json_url])
        mx.log(f"Synced {common_json_path}")
        common_jsonnet_path = os.path.join(mx._mx_suite.dir, "ci", "common.jsonnet")
        mx.download(common_jsonnet_path, [common_jsonnet_url])
        mx.log(f"Synced {common_jsonnet_path}")
