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

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mx._impl import mx, mx_multiplatform  # pylint: disable=no-name-in-module


class MultiplatformTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.local = mx_multiplatform._local_os_arch()
        self.variant = self.local + "-test-variant"
        self.dist = Mock(spec=mx.LayoutDirDistribution)
        self.dist.name = "RESOURCES"
        self.dist.platformDependent = True
        self.dist.local_platform_only = False
        self.dist.platforms = [self.local, self.variant]
        self.output = self.root / self.local / self.dist.name
        self.output.mkdir(parents=True)
        self.dist.get_output.return_value = str(self.output)
        self.dist.getArchivableResults.side_effect = lambda: mx.LayoutDirDistribution.getArchivableResults(self.dist)
        self.archive = str(self.root / "resources.tgz")
        self.opts = SimpleNamespace(multi_platform_layout_directories=None, verbose=False, very_verbose=False)
        for mocked in (
            patch.object(mx, "_opts", self.opts),
            patch.object(mx, "get_opts", return_value=self.opts),
            patch.object(mx, "distributions", return_value=[self.dist]),
            patch.object(mx, "distribution", side_effect=self.distribution),
            patch.object(mx, "primary_suite", return_value=SimpleNamespace(dir=str(self.root))),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def distribution(self, name, **_kwargs):
        if name == self.dist.name:
            return self.dist
        mx.abort("Unknown distribution: " + name)

    def export(self, *options):
        mx_multiplatform.mx_archive_pd_layouts([*options, self.archive])

    def test_variant_round_trip_and_union(self):
        (self.output / "variant").mkdir()
        (self.output / "variant" / "native").write_text("swcfi", encoding="utf-8")
        # Unselected distributions need neither this platform nor an output directory.
        unselected = Mock(spec=mx.LayoutDirDistribution, platformDependent=True, local_platform_only=False)
        with patch.object(mx, "distributions", return_value=[self.dist, unselected]):
            self.export("--platform-id=" + self.variant, "--only=RESOURCES")
        shutil.rmtree(self.output)
        self.output.mkdir()
        (self.output / "native").write_text("default", encoding="utf-8")
        mx_multiplatform.mx_restore_pd_layouts([self.archive])
        self.assertEqual(self.output.joinpath("native").read_text(encoding="utf-8"), "default")
        self.opts.multi_platform_layout_directories = self.local + "," + self.variant
        contents = {name: Path(path).read_text(encoding="utf-8") for path, name in self.dist.getArchivableResults()}
        self.assertEqual(contents, {"native": "default", str(Path("variant") / "native"): "swcfi"})

    def test_legacy_round_trip(self):
        (self.output / "native").write_text("default", encoding="utf-8")
        self.export()
        (self.output / "native").unlink()
        mx_multiplatform.mx_restore_pd_layouts([self.archive])
        self.assertEqual(self.output.joinpath("native").read_text(encoding="utf-8"), "default")

    def test_invalid_selection(self):
        for options in (
            ["--platform-id=../../escape"],
            ["--platform-id=linux-unknown"],
            ["--only=UNKNOWN"],
            ["--only="],
        ):
            with self.subTest(options=options), self.assertRaises(SystemExit):
                self.export(*options)

    def test_missing_output(self):
        self.output.rmdir()
        with self.assertRaises(SystemExit):
            self.export("--only=RESOURCES")

    def test_reject_merged_export(self):
        self.opts.multi_platform_layout_directories = "all"
        with self.assertRaises(SystemExit):
            self.export()

    def test_union_rejects_conflicting_contents(self):
        (self.output / "native").write_text("swcfi", encoding="utf-8")
        self.export("--platform-id=" + self.variant)
        mx_multiplatform.mx_restore_pd_layouts([self.archive])
        (self.output / "native").write_text("default", encoding="utf-8")
        self.opts.multi_platform_layout_directories = "all"
        with self.assertRaises(SystemExit):
            list(self.dist.getArchivableResults())


if __name__ == "__main__":
    unittest.main()
