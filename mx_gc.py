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

import mx
from datetime import datetime, date, timedelta


def _format_datetime(dt):

    def _fmt(num, unit):
        return "{:.0f} {}".format(num, unit)

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
        return "{:.0f} {}".format(num, unit)

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
                raise ValueError('argument {}: value {} does not match format {}'.format(option_string, values, TimeAction.fmt))
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
                raise ValueError('argument {}: Unexpected unit: {}'.format(option_string, unit))
            td = datetime.today() - timedelta(minutes=minutes)
            setattr(namespace, self.dest, td)


@mx.command('mx', 'gc-dists')
def gc_dists(args):
    """ Garbage collect mx distributions."""

    parser = argparse.ArgumentParser(prog='mx gc-dists', description='''Garbage collect layout distributions.
        By default, it collects all found layout distributions that are *not* part of the current configuration (see `--keep-current`).
        This command respects mx level suite filtering (e.g., `mx --suite my-suite gc-dists`).
        ''', epilog='''If the environment variable `MX_GC_AFTER_BUILD` is set, %(prog)s will be executed after `mx build`
        using the content of the environment variable as parameters.''')
    # mutually exclusive groups do not support title and description - wrapping in another group as a workaround
    action_group_desc = parser.add_argument_group('actions', 'What to do with the result. One of the following arguments is required.')
    action_group = action_group_desc.add_mutually_exclusive_group(required=True)
    action_group.add_argument('-f', '--force', action='store_true', help='remove layout distributions without further questions')
    action_group.add_argument('-n', '--dry-run', action='store_true', help='show what would be removed without actually doing anything')
    action_group.add_argument('-i', '--interactive', action='store_true', help='ask for every layout distributions whether it should be removed')
    keep_current_group_desc = parser.add_argument_group('current configuration handling', description='How to deal with the current configuration, i.e., what `mx build` would rebuild.')
    keep_current_group = keep_current_group_desc.add_mutually_exclusive_group()
    keep_current_group.add_argument('--keep-current', action='store_true', default=True, help='keep layout distributions of the current configuration (default)')
    keep_current_group.add_argument('--no-keep-current', action='store_false', dest='keep_current', help='remove layout distributions of the current configuration')
    filter_group = parser.add_argument_group('result filters', description='Filter can be combined.')
    filter_group.add_argument('--reverse', action='store_true', help='reverse the result')
    filter_group.add_argument('--older-than', action=TimeAction, help='only show results older than the specified point in time (format: {})'.format(TimeAction.fmt.replace('%', '%%')))
    try:
        parsed_args = parser.parse_args(args)
    except ValueError as ve:
        parser.error(str(ve))
    suites = mx.suites(opt_limit_to_suite=True, includeBinary=False, include_mx=False)
    c = []

    for s in suites:
        c += _gc_layout_dists(s, parsed_args)

    if not c:
        mx.log("Nothing to do!")
        return

    if parsed_args.older_than:
        c = [x for x in c if x[1] < parsed_args.older_than]
    # sort by mod date
    c = sorted(c, key=lambda x: x[1], reverse=parsed_args.reverse)

    # calculate max sizes
    max_path = 0
    max_mod_time = 0
    max_size = 0
    for path, mod_time, size in c:
        max_path = max(len(path), max_path)
        max_mod_time = max(len(_format_datetime(mod_time)), max_mod_time)
        max_size = max(len(_format_bytes(size)), max_size)

    msg_fmt = '{0:<' + str(max_path) + '} modified {1:<' + str(max_mod_time + len(' ago')) +'}  {2:<' + str(max_size) + '}'

    size_sum = 0
    for path, mod_time, size in c:
        if parsed_args.dry_run:
            mx.log(msg_fmt.format(path, _format_datetime(mod_time) + ' ago', _format_bytes(size)))
            size_sum += size
        else:
            msg = '{0}   (modified {1} ago, size {2})'.format(path, _format_datetime(mod_time), _format_bytes(size))
            if parsed_args.force or parsed_args.interactive and mx.ask_yes_no('Delete ' + msg):
                mx.log('rm ' + path)
                mx.rmtree(path)
                size_sum += size

    if parsed_args.dry_run:
        mx.log('Would free ' + _format_bytes(size_sum))
    else:
        mx.log('Freed ' + _format_bytes(size_sum))


def _gc_layout_dists(suite, parsed_args):
    """Returns a list of collected layout distributions as a tuples of form (path, modification time, size in bytes)."""
    mx.logv("GC layout distributions of suite " + suite.name)
    known_dists = [d.name for d in suite.dists if d.isLayoutDistribution()] if parsed_args.keep_current else []

    def _to_archive_name(d):
        return d.lower().replace("_", "-")

    # We use 'savedLayouts' to identify layout distributions. Whenever mx builds a layout distribution, this file is updated.
    saved_layouts_dir = os.path.join(suite.get_mx_output_dir(), "savedLayouts")
    if not os.path.exists(saved_layouts_dir):
        return []
    found_dists = [d for d in _listdir(saved_layouts_dir) if os.path.isfile(os.path.join(saved_layouts_dir, d))]
    candidates = {}
    # search for the layout distribution folder as well as for the archive, platform dependent and independent
    for platformDependent in [True, False]:
        # we use modification time of the saved layouts file since that is the canonical modified time
        unknown_dists = {d: datetime.fromtimestamp(os.path.getmtime(os.path.join(saved_layouts_dir, d))) for d in found_dists if d not in known_dists}
        dist_dir = suite.get_output_root(platformDependent=platformDependent)
        candidates.update({os.path.join(dist_dir, x): x for x in _listdir(dist_dir) if x in unknown_dists.keys()})

        for ext in [".tar", ".zip"]:
            unknown_archives = {_to_archive_name(d) + ext: d for d in unknown_dists.keys()}
            archive_dir = os.path.join(dist_dir, "dists")
            candidates.update({os.path.join(archive_dir, x): unknown_archives.get(x) for x in _listdir(archive_dir) if x in unknown_archives.keys()})
    return [(k, unknown_dists.get(v), _get_size_in_bytes(k)) for k, v in candidates.items()]
