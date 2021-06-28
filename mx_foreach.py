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
import mx


@mx.command('mx', 'foreach-repo')
def foreach_repo(args):
    """Run a command in the root of all repos of imported suites."""

    parser = argparse.ArgumentParser(prog='mx foreach-repo',
                                     description='''Run a command in the root of all repos of imported suites.''',
                                     usage='%(prog)s [options] [--] command...')
    parser.add_argument('-n', '--dry-run', action='store_true', help='show what would be removed without actually doing anything')

    try:
        sep_idx = args.index('--')
        parsed_args = parser.parse_args(args[:sep_idx])
        remaining_args = args[(sep_idx + 1):]
    except ValueError:
        parsed_args, remaining_args = parser.parse_known_args(args)

    p = mx.primary_suite()
    suites = [p] + [mx.suite(i.name) for i in p.suite_imports]
    vc_dirs = []
    # ensure that we preserve the order
    for x in suites:
        if x.vc_dir not in vc_dirs:
            vc_dirs.append(x.vc_dir)

    def _log_cwd(msg):
        mx.log(mx.colorize(msg, color='cyan'))

    def _log_exec(msg):
        mx.log(mx.colorize(msg, color='green'))

    cmd = remaining_args
    if len(cmd) == 0:
        mx.abort(f'{parser.prog} requires a command...\n\n{parser.format_usage()}')
    for vc_dir in vc_dirs:
        _log_cwd('Entering directory `{}`'.format(vc_dir))
        try:
            if parsed_args.dry_run:
                _log_exec('Would run: {}'.format(' '.join(cmd)))
            else:
                _log_exec('Running: {}'.format(' '.join(cmd)))
                mx.run(cmd, cwd=vc_dir)
        finally:
            _log_cwd('Leaving directory `{}`'.format(vc_dir))
