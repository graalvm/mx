#!/usr/bin/env python
#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2018, Oracle and/or its affiliates. All rights reserved.
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

from __future__ import print_function

import subprocess
import re
from argparse import ArgumentParser
from os.path import realpath, dirname

parser = ArgumentParser(usage='%(prog)s [options]\n\n' + """
Finds the mx version update denoted in the diff of mx.py between the <descendant>
and <ancestor> commits and tags <descendant> with the new version. Exits with non-zero
if diff does not contain an mx version update.
""")
parser.add_argument('--check-only', action='store_true', help='do not apply tag')
parser.add_argument('descendant', action='store', help='descendant commit for diff', metavar='<descendant>')
parser.add_argument('ancestor', action='store', nargs='?', default=None, help='ancestor commit for diff', metavar='<ancestor>')
args = parser.parse_args()

mx_home = realpath(dirname(__file__))
old_version_re = re.compile(r'.*\-version = VersionSpec\("([^"]+)"\).*', re.DOTALL)
new_version_re = re.compile(r'.*\+version = VersionSpec\("([^"]+)"\).*', re.DOTALL)

def _check_output_str(*args, **kwargs):
    return subprocess.check_output(*args, **kwargs).decode()

def get_parents(commit):
    return subprocess.check_output(['git', 'rev-parse', commit + '^@']).decode().strip().split()

def with_hash(commit):
    h = _check_output_str(['git', 'rev-parse', commit]).strip()
    if h == commit:
        return h
    return '{} ({})'.format(commit, h)


parents = get_parents(args.descendant)
if args.ancestor:
    # https://stackoverflow.com/a/18345268/6691595
    if subprocess.call(['git', 'merge-base', '--is-ancestor', args.ancestor, args.descendant], cwd=mx_home) != 0:
        raise SystemExit('{} is not an ancestor of {}'.format(with_hash(args.ancestor), with_hash(args.descendant)))
    if len(parents) > 1:
        raise SystemExit('{} cannot be a merge commit'.format(with_hash(args.descendant)))
else:
    # Find sole merge parent that is a merge itself
    for candidate in parents:
        if len(get_parents(candidate)) > 1:
            if args.ancestor:
                raise SystemExit('Both parents of {} are merges ({} and {}). '.format(with_hash(args.descendant), candidate, with_hash(args.ancestor)) +
                                 'This makes it impossible to determine which parent is the from the master branch. ' +
                                 'Please ensure the tip of your pull request is not a merge commit. ' +
                                 'The simplest solution is to edit history such that the commit with the version bump is the tip commit.')
            args.ancestor = candidate
    if not args.ancestor:
        raise SystemExit('{} is not a merge or has no parent that is a merge'.format(with_hash(args.descendant)))

diff = _check_output_str(['git', 'diff', args.ancestor, args.descendant, '--', 'mx.py'], cwd=mx_home).strip()
new_version = new_version_re.match(diff)
old_version = old_version_re.match(diff)


def version_to_ints(spec):
    try:
        return [int(e) for e in spec.split('.')]
    except ValueError as e:
        raise SystemExit('{} is not a valid mx version string: {}'.format(spec, str(e)))


if new_version and old_version:
    tag = new_version.group(1)
    old_tag = old_version.group(1)
    print('Found update of mx version from {} to {}'.format(old_tag, tag))
    old = version_to_ints(old_tag)
    new = version_to_ints(tag)
    if old >= new:
        raise SystemExit('Version update does not go forward')
    if not args.check_only:
        subprocess.check_call(['git', 'tag', tag, args.descendant])
        subprocess.check_call(['git', 'push', 'origin', tag])
else:
    raise SystemExit('Could not find mx version update in the diff between {} and {}:\n{}\n\nPlease bump the value of the `version` field near the bottom of mx.py.'.format(with_hash(args.ancestor), with_hash(args.descendant), diff))
