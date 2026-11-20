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
import io
import os
import sys
import tempfile
import unittest
from argparse import Action
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
mx_unittest = importlib.import_module("mx._impl.mx_unittest")


class UnittestOptionsTest(unittest.TestCase):
    def test_normal_help_hides_legacy_options(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            mx_unittest.unittest(["--help"])
        self.assertEqual(exit_context.exception.code, 0)
        help_text = output.getvalue()
        for option in ("--include-list", "--exclude-list"):
            self.assertIn(option, help_text)
        for option in ("--whitelist", "--blacklist", "--help-legacy"):
            self.assertNotIn(option, help_text)

    def test_filter_option_aliases(self):
        candidates = {"example.FirstTest": "example", "other.SecondTest": "other"}
        launcher = Mock()
        launcher.jdk.return_value.javaCompliance = "25"
        with tempfile.TemporaryDirectory() as tmpdir:
            test_list = Path(tmpdir) / "tests.txt"
            selected_tests = Path(tmpdir) / "selected.txt"
            test_list.write_text("# comment\nexample.*Test\n", encoding="utf-8")
            for option, expected in (
                ("--include-list", "example.FirstTest"),
                ("--whitelist", "example.FirstTest"),
                ("--exclude-list", "other.SecondTest"),
                ("--blacklist", "other.SecondTest"),
            ):
                with self.subTest(option=option), patch.dict(
                    os.environ, {"MX_TESTFILE": str(selected_tests)}
                ), patch.object(mx_unittest, "_vm_launcher", launcher), patch.object(
                    mx_unittest, "find_test_candidates", return_value=candidates
                ), patch.object(
                    mx_unittest, "resolve_unittest_configs", return_value=([], lambda config: config)
                ), patch.multiple(
                    mx_unittest.mx,
                    build=Mock(),
                    classpath=Mock(return_value=""),
                    get_runtime_jvm_args=Mock(return_value=[]),
                ):
                    mx_unittest.unittest([option, str(test_list), "--"])
                    self.assertEqual(selected_tests.read_text(encoding="utf-8").splitlines(), [expected])
                    selected_tests.unlink()

    def test_suite_action_can_read_and_write_legacy_attributes(self):
        def check_aliases(namespace, include, exclude):
            self.assertEqual(namespace.whitelist, include)
            self.assertEqual(namespace.blacklist, exclude)
            self.assertEqual(namespace.include_list, include)
            self.assertEqual(namespace.exclude_list, exclude)

        class OverrideFilters(Action):
            def __call__(self, parser, namespace, values, option_string=None):
                check_aliases(namespace, "original-include", "original-exclude")
                namespace.whitelist, namespace.blacklist = values
                check_aliases(namespace, *values)

        with tempfile.TemporaryDirectory() as tmpdir:
            include = Path(tmpdir) / "include.txt"
            exclude = Path(tmpdir) / "exclude.txt"
            include.write_text("example.*Test\n", encoding="utf-8")
            exclude.write_text("other.*Test\n", encoding="utf-8")
            args = [
                "--include-list",
                "original-include",
                "--blacklist",
                "original-exclude",
                "--override-filters",
                str(include),
                str(exclude),
            ]
            with patch.object(mx_unittest, "_extra_unittest_arguments", []):
                mx_unittest.add_unittest_argument("--override-filters", nargs=2, action=OverrideFilters)
                for suffix in ([], ["--"]):
                    with self.subTest(suffix=suffix), patch.object(mx_unittest, "_unittest") as run:
                        mx_unittest.unittest(args + suffix)
                        run.assert_called_once()
                        filters = run.call_args.kwargs
                        self.assertIsNotNone(filters["include_list"][0].fullmatch("example.FirstTest"))
                        self.assertIsNotNone(filters["exclude_list"][0].fullmatch("other.SecondTest"))
                        self.assertNotIn("whitelist", filters)
                        self.assertNotIn("blacklist", filters)
