#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2026, Oracle and/or its affiliates. All rights reserved.
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

import importlib
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

orig_logging = importlib.import_module("mx._impl.support.logging")
ansi_escape_pattern = re.compile(r"\033\[[0-?]*[ -/]*[@-~]")


class StatuslineFormattingTest(unittest.TestCase):
    def test_pad_and_truncate_for_terminal_ignores_ansi_escape_sequences(self):
        statusline = "[\033[31;1m1\033[0m/\033[34;1m2\033[0m/\033[32;1m3\033[0m] build"

        aligned = orig_logging._pad_and_truncate_for_terminal(statusline, 12)

        self.assertEqual(ansi_escape_pattern.sub("", aligned), "[1/2/3] buil")

    def test_pad_and_truncate_for_terminal_preserves_full_visible_width(self):
        statusline = "[\033[31;1m1\033[0m/\033[34;1m2\033[0m/\033[32;1m3\033[0m]"

        aligned = orig_logging._pad_and_truncate_for_terminal(statusline, 12)

        self.assertEqual(ansi_escape_pattern.sub("", aligned), "[1/2/3]     ")

    def test_pad_and_truncate_for_terminal_does_not_add_reset_without_ansi(self):
        aligned = orig_logging._pad_and_truncate_for_terminal("plain text", 5)

        self.assertEqual(aligned, "plain")


if __name__ == "__main__":
    unittest.main()
