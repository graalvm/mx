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
import sys
import tempfile
import unittest

from contextlib import contextmanager
from argparse import Namespace
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

orig_mx = importlib.import_module("mx._impl.mx")
mx_gc = importlib.import_module("mx._impl.mx_gc")


@contextmanager
def monkeypatch_attr(obj, name, value):
    previous = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        setattr(obj, name, previous)


class GcCacheTest(unittest.TestCase):
    def test_keep_current_excludes_entries_referenced_by_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = pathlib.Path(tmpdir) / "cache"
            cache_dir.mkdir()
            current_entry = cache_dir / "LIB_1234"
            current_entry.mkdir()
            (current_entry / "library.jar").write_text("library", encoding="utf-8")
            current_source_entry = cache_dir / "LIB_SOURCES_1234"
            current_source_entry.mkdir()
            (current_source_entry / "library-sources.jar").write_text("sources", encoding="utf-8")
            stale_entry = cache_dir / "OLD_LIB_1234"
            stale_entry.mkdir()
            (stale_entry / "old-library.jar").write_text("old", encoding="utf-8")

            deps = [
                SimpleNamespace(
                    path=str(current_entry / "library.jar"),
                    sourcePath=str(current_source_entry / "library-sources.jar"),
                    extract_path=None,
                )
            ]
            with monkeypatch_attr(orig_mx, "_CACHE_DIR", str(cache_dir)):
                with monkeypatch_attr(orig_mx, "dependencies", lambda: deps):
                    with monkeypatch_attr(orig_mx, "run_mx", lambda args, **kwargs: 0):
                        candidates = mx_gc._gc_cache_entries(Namespace(keep_current=True))

        candidate_paths = {pathlib.Path(candidate.path).name for candidate in candidates}
        self.assertEqual({"OLD_LIB_1234"}, candidate_paths)

    def test_no_keep_current_collects_referenced_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = pathlib.Path(tmpdir) / "cache"
            cache_dir.mkdir()
            current_entry = cache_dir / "LIB_1234"
            current_entry.mkdir()
            (current_entry / "library.jar").write_text("library", encoding="utf-8")

            with monkeypatch_attr(orig_mx, "_CACHE_DIR", str(cache_dir)):
                candidates = mx_gc._gc_cache_entries(Namespace(keep_current=False))

        candidate_paths = {pathlib.Path(candidate.path).name for candidate in candidates}
        self.assertEqual({"LIB_1234"}, candidate_paths)

    def test_keep_current_excludes_fetch_jdk_cache_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = pathlib.Path(tmpdir) / "cache"
            cache_dir.mkdir()
            current_jdk_entry = cache_dir / "labsjdk-ce-21-jvmci-23.1-b33_1234"
            current_jdk_entry.mkdir()
            (current_jdk_entry / "labsjdk.tar.gz").write_text("jdk", encoding="utf-8")
            stale_entry = cache_dir / "labsjdk-ce-20-jvmci-23.1-b02_1234"
            stale_entry.mkdir()
            (stale_entry / "labsjdk.tar.gz").write_text("old-jdk", encoding="utf-8")

            def fake_run_mx(args, **kwargs):
                self.assertEqual(["fetch-jdk", "--list-cache-paths"], args)
                kwargs["out"](str(cache_dir / "labsjdk-ce-21-jvmci-23.1-b33_*") + "\n")
                return 0

            with monkeypatch_attr(orig_mx, "_CACHE_DIR", str(cache_dir)):
                with monkeypatch_attr(orig_mx, "dependencies", lambda: []):
                    with monkeypatch_attr(orig_mx, "run_mx", fake_run_mx):
                        candidates = mx_gc._gc_cache_entries(Namespace(keep_current=True))

        candidate_paths = {pathlib.Path(candidate.path).name for candidate in candidates}
        self.assertEqual({"labsjdk-ce-20-jvmci-23.1-b02_1234"}, candidate_paths)

    def test_missing_cache_dir_has_no_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = pathlib.Path(tmpdir) / "missing-cache"

            with monkeypatch_attr(orig_mx, "_CACHE_DIR", str(cache_dir)):
                candidates = mx_gc._gc_cache_entries(Namespace(keep_current=True))

        self.assertEqual([], candidates)


if __name__ == "__main__":
    unittest.main()
