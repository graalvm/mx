#
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
#
import os
import shutil
from argparse import ArgumentParser
from os.path import join, exists, dirname

import mx


def _local_os_arch():
    return f"{mx.get_os()}-{mx.get_arch()}"


@mx.command('mx', 'archive-pd-layouts', '<archive-path>')
def mx_archive_pd_layouts(args):
    parser = ArgumentParser(prog='mx archive-pd-layouts', description="""Create an archive containing the output of platform-dependent layout directory distributions.
See mx restore-pd-layouts and --multi-platform-layout-directories.""")
    parser.add_argument('path', help='path to archive')
    args = parser.parse_args(args)
    archive_path = os.path.realpath(args.path)

    ext = mx.get_file_extension(archive_path)
    if ext not in ('zip', 'jar', 'tar', 'tgz'):
        raise mx.abort("Unsupported archive extension. Supported: .zip, .jar, .tar, .tgz")

    pd_layout_dirs = [d for d in mx.distributions(True) if isinstance(d, mx.LayoutDirDistribution) and d.platformDependent]
    with mx.Archiver(archive_path, kind=ext) as arc:
        local_os_arch = _local_os_arch()
        arc.add_str(local_os_arch, "os-arch", None)
        for dist in pd_layout_dirs:
            if local_os_arch not in dist.platforms:
                raise mx.abort(f"{dist.name} doesn't list {local_os_arch} in its 'platforms' attribute")
            mx.log(f"Adding {dist.name}...")
            for file_path, arc_name in dist.getArchivableResults():
                arc.add(file_path, f"{dist.name}/{arc_name}", dist.name)


@mx.command('mx', 'restore-pd-layouts', '<archive-path>')
def mx_restore_pd_layouts(args):
    parser = ArgumentParser(prog='mx restore-pd-layouts', description="""Restore the output of platform-dependent layout directory distributions.
See mx archive-pd-layouts and --multi-platform-layout-directories.""")
    parser.add_argument('--ignore-unknown-distributions', action='store_true')
    parser.add_argument('path', help='path to archive')
    args = parser.parse_args(args)

    local_os_arch = _local_os_arch()
    with mx.TempDir(parent_dir=mx.primary_suite().dir) as tmp:
        mx.Extractor.create(args.path).extract(tmp)
        with open(join(tmp, 'os-arch'), 'r') as f:
            os_arch = f.read().strip()
        if local_os_arch == os_arch:
            mx.warn("Restoring archive from the current platform")
        with os.scandir(tmp) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False) and entry.name == "os-arch":
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    raise mx.abort(f"Unexpected file in archive: {entry.name}")
                dist = mx.distribution(entry.name, fatalIfMissing=not args.ignore_unknown_distributions)
                if not dist:
                    continue
                if not isinstance(dist, mx.LayoutDirDistribution) or not dist.platformDependent:
                    raise mx.abort(f"{entry.name} is not a platform-dependent layout dir distribution")
                local_output = dist.get_output()
                assert local_os_arch in local_output
                mx.log(f"Restoring {dist.name}...")
                foreign_output = local_output.replace(local_os_arch, os_arch)
                if exists(foreign_output):
                    mx.rmtree(foreign_output)
                mx.ensure_dir_exists(dirname(foreign_output))
                shutil.move(join(tmp, entry.name), foreign_output)
