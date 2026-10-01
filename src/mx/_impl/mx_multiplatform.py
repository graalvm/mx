#
# ----------------------------------------------------------------------------------------------------
#
# pylint: disable=raising-bad-type

# Copyright (c) 2023, 2026, Oracle and/or its affiliates. All rights reserved.
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
import re
import shutil
from argparse import ArgumentParser
from os.path import join, exists, dirname

from . import mx, mx_util


def _local_os_arch():
    return f"{mx.get_os()}-{mx.get_arch()}"


def _validate_platform_id(platform_id):
    # This value becomes part of an output directory on restore.
    if not re.fullmatch(r'[a-z0-9_]+-[a-z0-9_]+(?:-[a-z0-9_]+)*', platform_id):
        mx.abort(f"Invalid platform ID: {platform_id!r}")
    return platform_id


@mx.command('mx', 'archive-pd-layouts', '[--platform-id=<id>] [--only=<distributions>] <archive-path>')
def mx_archive_pd_layouts(args):
    parser = ArgumentParser(prog='mx archive-pd-layouts', description="""Create an archive containing the output of platform-dependent layout directory distributions.
See mx restore-pd-layouts and --multi-platform-layout-directories.""")
    parser.add_argument('--platform-id', default=_local_os_arch(),
                        help='platform identity recorded in the archive (default: host OS-architecture)')
    parser.add_argument('--only', help='comma-separated layout directory distribution names to export')
    parser.add_argument('path', help='path to archive')
    args = parser.parse_args(args)
    platform_id = _validate_platform_id(args.platform_id)
    archive_path = os.path.realpath(args.path)
    if mx.get_opts().multi_platform_layout_directories:
        mx.abort('archive-pd-layouts must export a single build, without --multi-platform-layout-directories')

    ext = mx_util.get_file_extension(archive_path)
    if ext not in ('zip', 'jar', 'tar', 'tgz', 'tar.gz'):
        raise mx.abort("Unsupported archive extension. Supported: .zip, .jar, .tar, .tgz, .tar.gz")

    pd_layout_dirs = [d for d in mx.distributions(True) if isinstance(d, mx.LayoutDirDistribution) and d.platformDependent and not d.local_platform_only]
    if args.only is not None:
        selected = [mx.distribution(name) for name in args.only.split(',')]
        for dist in selected:
            if dist not in pd_layout_dirs:
                mx.abort(f'{dist.name} is not an exportable platform-dependent layout directory distribution')
        pd_layout_dirs = selected
    for dist in pd_layout_dirs:
        if platform_id not in dist.platforms:
            mx.abort(f"{dist.name} doesn't list {platform_id} in its 'platforms' attribute")
        if not os.path.isdir(dist.get_output()):
            mx.abort(f'Missing output directory for {dist.name}: {dist.get_output()}')
    with mx.Archiver(archive_path, kind=ext) as arc:
        arc.add_str(platform_id, "os-arch", None)
        for dist in pd_layout_dirs:
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
        with open(join(tmp, 'os-arch'), 'r', encoding='utf-8') as f:
            os_arch = _validate_platform_id(f.read().strip())
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
                mx_util.ensure_dir_exists(dirname(foreign_output))
                shutil.move(join(tmp, entry.name), foreign_output)
