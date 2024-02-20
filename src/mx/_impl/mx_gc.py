#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2021, Oracle and/or its affiliates. All rights reserved.
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
import argparse
import os
import re

from . import mx, mx_fetchjdk
from datetime import datetime, date, timedelta


def _format_datetime(dt):

    def _fmt(num, unit):
        return f"{num:.0f} {unit}"

    diff = datetime.now() - dt
    num = diff.total_seconds()
    for unit, top, max_num in [
        ('seconds', 60, 120),
        ('minutes', 60, 120),
        ('hours', 24, 48),
        ('days', 365, 365),
    ]:
        if num < max_num:
            return _fmt(num, unit)
        num /= top
    unit = "years"
    return _fmt(num, unit)


def _format_bytes(num):

    def _fmt(num, unit):
        return f"{num:.0f} {unit}"

    for unit in ['Byte', 'KiB', 'MiB', 'GiB']:
        if num < 1024.0:
            return _fmt(num, unit)
        num /= 1024.0
    unit = 'TiB'
    return _fmt(num, unit)

_has_scandir = 'scandir' in dir(os)
def _get_size_in_bytes(path, isdir=None):
    if isdir is None:
        if not os.path.exists(path) or os.path.islink(path):
            return 0
    if isdir or os.path.isdir(path):
        if not _has_scandir:
            return sum(_get_size_in_bytes(os.path.join(path, f)) for f in os.listdir(path))
        s = 0
        with os.scandir(path) as it:
            for e in it:
                if not e.is_symlink():
                    if e.is_dir(follow_symlinks=False):
                        s += _get_size_in_bytes(e.path, isdir=True)
                    else:
                        s += e.stat(follow_symlinks=False).st_size
        return s
    return os.path.getsize(path)

def _listdir(path):
    if os.path.isdir(path):
        return [p for p in os.listdir(path) if not os.path.islink(p)]
    return []

class TimeAction(argparse.Action):
    pattern = re.compile(r'^(?:(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?T?(?:(?P<hour>\d\d):(?P<minute>\d\d)(?::(?P<second>\d\d))?)?$')
    rel_pattern = re.compile(r'^(?P<value>\d+)(?P<unit>min?u?t?e?|da?y?|we?e?k?|mon?t?h?|ye>a>r?)s?$')
    fmt = r'%Y-%m-%dT%H:%M:%S or [0-9]+(minutes|days|weeks|months|years)'

    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super(TimeAction, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        m = TimeAction.pattern.match(values)
        if m:
            # default values: today 00:00
            today = datetime.combine(date.today(), datetime.min.time())
            date_dict = {k: int(v or getattr(today, k)) for k, v in m.groupdict().items()}
            td = datetime(**date_dict)
            setattr(namespace, self.dest, td)
        else:
            m = TimeAction.rel_pattern.match(values)
            if not m:
                raise ValueError(f'argument {option_string}: value {values} does not match format {TimeAction.fmt}')
            minutes_per_day = 24 * 60
            unit = m.group('unit')
            value = int(m.group('value'))
            if unit.startswith('y'):
                minutes = value * 365 * minutes_per_day
            elif unit.startswith('mo'):
                minutes = value * 30 * minutes_per_day
            elif unit.startswith('w'):
                value += 7 * minutes_per_day
            elif unit.startswith('d'):
                minutes = value * minutes_per_day
            elif unit.startswith('mi'):
                minutes = value
            else:
                raise ValueError(f'argument {option_string}: Unexpected unit: {unit}')
            td = datetime.today() - timedelta(minutes=minutes)
            setattr(namespace, self.dest, td)


class CollectionCandidate(object):
    def __init__(self, path, modification_time, size_in_bytes):
        self.path = path
        self.modification_time = modification_time
        self.size_in_bytes = size_in_bytes


def _gc_collect_generic(args, parser, collect_candidates):
    # mutually exclusive groups do not support title and description - wrapping in another group as a workaround
    action_group_desc = parser.add_argument_group('actions',
                                                  'What to do with the result. One of the following arguments is required.')
    action_group = action_group_desc.add_mutually_exclusive_group(required=True)
    action_group.add_argument('-f', '--force', action='store_true',
                              help='remove candidates without further questions')
    action_group.add_argument('-n', '--dry-run', action='store_true',
                              help='show what would be removed without actually doing anything')
    action_group.add_argument('-i', '--interactive', action='store_true',
                              help='ask for every candidate whether it should be removed')
    keep_current_group_desc = parser.add_argument_group('current configuration handling',
                                                        description='How to deal with the current configuration, i.e., what `mx build` would rebuild.')
    keep_current_group = keep_current_group_desc.add_mutually_exclusive_group()
    keep_current_group.add_argument('--keep-current', action='store_true', default=True,
                                    help='keep candidate referenced by current configuration (default)')
    keep_current_group.add_argument('--no-keep-current', action='store_false', dest='keep_current',
                                    help='remove candidate referenced by the current configuration')
    filter_group = parser.add_argument_group('result filters', description='Filter can be combined.')
    filter_group.add_argument('--reverse', action='store_true', help='reverse the result')
    filter_group.add_argument('--older-than', action=TimeAction,
                              help=f"only show results older than the specified point in time (format: {TimeAction.fmt.replace('%', '%%')})")
    try:
        parsed_args = parser.parse_args(args)
    except ValueError as ve:
        parser.error(str(ve))
        return
    candidates = collect_candidates(parsed_args)
    if not candidates:
        mx.log("Nothing to do!")
        return
    if parsed_args.older_than:
        candidates = [x for x in candidates if x.modification_time < parsed_args.older_than]
    # sort by mod date
    candidates = sorted(candidates, key=lambda x: x.modification_time, reverse=parsed_args.reverse)
    # calculate max sizes
    max_path = 0
    max_mod_time = 0
    max_size = 0
    for candidate in candidates:
        path = candidate.path
        mod_time = candidate.modification_time
        size = candidate.size_in_bytes
        max_path = max(len(path), max_path)
        max_mod_time = max(len(_format_datetime(mod_time)), max_mod_time)
        max_size = max(len(_format_bytes(size)), max_size)

    msg_fmt = '{0:<' + str(max_path) + '} modified {1:<' + str(max_mod_time + len(' ago')) +'}  {2:<' + str(max_size) + '}'

    size_sum = 0
    for candidate in candidates:
        path = candidate.path
        mod_time = candidate.modification_time
        size = candidate.size_in_bytes
        if parsed_args.dry_run:
            mx.log(msg_fmt.format(path, _format_datetime(mod_time) + ' ago', _format_bytes(size)))
            size_sum += size
        else:
            msg = f'{path}   (modified {_format_datetime(mod_time)} ago, size {_format_bytes(size)})'
            if parsed_args.force or parsed_args.interactive and mx.ask_yes_no('Delete ' + msg):
                mx.log('rm ' + path)
                mx.rmtree(path)
                size_sum += size
    if parsed_args.dry_run:
        mx.log('Would free ' + _format_bytes(size_sum))
    else:
        mx.log('Freed ' + _format_bytes(size_sum))


@mx.command('mx', 'gc-dists')
def gc_dists(args):
    """ Garbage collect mx distributions."""

    parser = argparse.ArgumentParser(prog='mx gc-dists', description='''Garbage collect layout distributions.
        By default, it collects all found layout distributions that are *not* part of the current configuration (see `--keep-current`).
        This command respects mx level suite filtering (e.g., `mx --suite my-suite gc-dists`).
        ''', epilog='''If the environment variable `MX_GC_AFTER_BUILD` is set, %(prog)s will be executed after `mx build`
        using the content of the environment variable as parameters.''')

    def _gc_collect_candidates(parsed_args):
        suites = mx.suites(opt_limit_to_suite=True, includeBinary=False, include_mx=False)
        c = []
        for s in suites:
            c += _gc_layout_dists(s, parsed_args)
        return c

    _gc_collect_generic(args, parser, _gc_collect_candidates)


def _gc_layout_dists(suite, parsed_args):
    """Returns a list of collected layout distributions as a tuples of form (path, modification time, size in bytes)."""
    mx.logv("GC layout distributions of suite " + suite.name)
    known_dists = [d.name for d in suite.dists if d.isLayoutDistribution()] if parsed_args.keep_current else []

    def _to_archive_name(d):
        return d.lower().replace("_", "-")

    # distribution name -> modification date
    found_dists = {}
    # We use 'savedLayouts' to identify layout distributions. Whenever mx builds a layout distribution, this file is updated.
    for dirpath, _, filenames in os.walk(suite.get_output_root(platformDependent=False, jdkDependent=False)):
        if os.path.basename(dirpath) == "savedLayouts":
            for filename in filenames:
                abs_filename = os.path.join(dirpath, filename)
                if os.path.isfile(abs_filename) and not os.path.islink(abs_filename):
                    # we use modification time of the saved layouts file since that is the canonical modified time
                    found_dists[filename] = datetime.fromtimestamp(os.path.getmtime(abs_filename))

    # distribution name -> modification date
    unknown_dists = {distname: moddate for distname, moddate in found_dists.items() if distname not in known_dists}

    # full artifact path -> dist
    candidates = {}
    # search for the layout distribution folder as well as for the archive, platform/jdk dependent and independent
    for jdkDependent in [True, False]:
        for platformDependent in [True, False]:
            dist_dir = suite.get_output_root(platformDependent=platformDependent, jdkDependent=jdkDependent)
            candidates.update({os.path.join(dist_dir, x): x for x in _listdir(dist_dir) if x in unknown_dists.keys()})

            for ext in [".tar", ".zip"]:
                unknown_archives = {_to_archive_name(d) + ext: d for d in unknown_dists.keys()}
                archive_dir = os.path.join(dist_dir, "dists")
                candidates.update({os.path.join(archive_dir, x): unknown_archives.get(x) for x in _listdir(archive_dir) if x in unknown_archives.keys()})
    return [CollectionCandidate(full_path, unknown_dists.get(dist), _get_size_in_bytes(full_path)) for full_path, dist in candidates.items()]


@mx.command('mx', 'gc-jdks')
def gc_jdks(args):
    """ Garbage collect mx distributions."""

    parser = argparse.ArgumentParser(prog='mx gc-jdks', description='''Garbage collect JDKs downloaded by mx fetch-jdk.
        By default, it collects all JDKs not referenced in common.json (see `--keep-current`).
        ''')

    def _gc_collect_candidates(parsed_args):
        """Returns a list of collected layout distributions as a tuples of form (path, modification time, size in bytes)."""
        settings = mx_fetchjdk._parse_args(["--list"])
        jdks_dir = settings["jdks-dir"]
        jdk_binaries = settings["jdk-binaries"]
        current_jdks = [jdk_binary.get_final_path(jdks_dir) for jdk_binary in jdk_binaries.values()]

        result = []
        for entry in os.listdir(jdks_dir):
            full_path = os.path.join(jdks_dir, entry)
            if parsed_args.keep_current and os.path.realpath(full_path) in current_jdks:
                continue
            modtime = datetime.fromtimestamp(os.path.getmtime(full_path))
            size = _get_size_in_bytes(full_path)
            result.append(CollectionCandidate(full_path, modtime, size))
        return result

    _gc_collect_generic(args, parser, _gc_collect_candidates)
