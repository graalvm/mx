#!/usr/bin/env python2.7
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
import subprocess, re
from argparse import ArgumentParser
from os.path import realpath, dirname

parser = ArgumentParser(usage='%(prog)s [options]\n\n' + """
Finds the mx version update denoted in the diff for <commit>
and tags <commit> with the new version. Exits with non-zero
if the commit does not contain an mx version update.
""")
parser.add_argument('--check-only', action='store_true', help='do not apply tag')
parser.add_argument('commit', action='store', help='commit to process', metavar='<commit>')
args = parser.parse_args()

mx_home = realpath(dirname(__file__))
old_version_re = re.compile(r'.*\-version = VersionSpec\("([^"]+)"\).*', re.DOTALL)
new_version_re = re.compile(r'.*\+version = VersionSpec\("([^"]+)"\).*', re.DOTALL)

diff = subprocess.check_output(['git', 'show', '-p', '-m', args.commit], cwd=mx_home).strip()
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
    print 'Found update of mx version from {} to {}'.format(old_tag, tag)
    old = version_to_ints(old_tag)
    new = version_to_ints(tag)
    if old >= new:
        raise SystemExit('Version update does not go forward')
    if not args.check_only:
        subprocess.check_call(['git', 'tag', tag, args.commit])
        subprocess.check_call(['git', 'push', 'origin', tag])
else:
    raise SystemExit('Could not find mx version update in this commit:\n{}'.format(diff))
