#!/usr/bin/env python2.7
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

import os, tempfile
from argparse import ArgumentParser, REMAINDER
from os.path import exists, expanduser, join, isdir, isfile, realpath, dirname
import StringIO

parser = ArgumentParser(prog='select_jdk', usage='%(prog)s [options] [<primary jdk> [<secondary jdk>...]]' + """
    Selects values for the JAVA_HOME, EXTRA_JAVA_HOMES and PATH environment variables based on
    the explicitly supplied JDKs or on system JDKs plus previously selected JDKs (cached in ~/.mx/jdk_cache).

    If the -s/--shell-source option is given, settings appropriate for the current shell are written to
    the given file such that it can be eval'ed in the shell to apply the settings. For example, in
    ~/.config/fish/config.fish:
    
        if test -x (dirname (which mx))/select_jdk.py
            function select_jdk
                set tmp_file (mktemp)
                eval (dirname (which mx))/select_jdk.py -s $tmp_file $argv
                source $tmp_file
                rm $tmp_file
            end
        end

    In the absence of -s, if the current directory looks like a suite, the mx.<suite>/env file is
    created/updated with the selected values for JAVA_HOME and EXTRA_JAVA_HOMES.

    Otherwise, the settings are printed such that they can applied manually.
""")

shell_setvar_format_default = 'export %s=%s'
shell_PATH_sep_default = os.pathsep
shell = os.environ.get('SHELL')
if shell.endswith('csh'):
    shell_setvar_format_default = 'setenv %s %s'
elif shell.endswith('fish'):
    shell_setvar_format_default = 'set -x %s %s'
    shell_PATH_sep_default = ' '

parser.add_argument('-s', '--shell-source', action='store', help='write settings to <path> for sourcing in calling shell', metavar='<path>')
parser.add_argument('--shell-setvar-format', action='store', help='format string for shell syntax to set a variable', metavar='<format>', default=shell_setvar_format_default)
parser.add_argument('--shell-PATH-sep', action='store', help='separator between elements when setting PATH value', metavar='<sep>', default=shell_PATH_sep_default)
parser.add_argument('jdks', nargs=REMAINDER, metavar='<primary jdk> [<secondary jdk>...]')

args = parser.parse_args()

def is_valid_jdk(jdk):
    java_exe = join(jdk, 'bin', 'java')
    if not exists(java_exe):
        java_exe += '.exe'
    return isfile(java_exe) and os.access(java_exe, os.X_OK)

def find_system_jdks():
    bases = [
        '/Library/Java/JavaVirtualMachines',
        '/usr/lib/jvm',
        '/usr/java',
        '/usr/jdk/instances',
        r'C:\Program Files\Java'
    ]
    jdks = set()
    for base in bases:
        if isdir(base):
            for n in os.listdir(base):
                jdk = join(base, n)
                mac_jdk = join(jdk, 'Contents', 'Home')
                if isdir(mac_jdk):
                    jdk = mac_jdk
                if is_valid_jdk(jdk):
                    jdks.add(realpath(jdk))
    return jdks

def get_suite_env_file():
    for n in os.listdir('.'):
        if n.startswith('mx.'):
            suite_py = join('.', n, 'suite.py')
            if exists(suite_py):
                return join('.', n, 'env')
    return None

def apply_selection(jdk, extra_jdks):
    source = StringIO.StringIO()
    print >> source, args.shell_setvar_format % ('JAVA_HOME', jdk)
    if extra_jdks:
        print >> source, args.shell_setvar_format % ('EXTRA_JAVA_HOMES', os.pathsep.join(extra_jdks))
    path = os.environ.get('PATH').split(os.pathsep)
    if path:
        jdk_bin = join(jdk, 'bin')
        old_java_home = os.environ.get('JAVA_HOME')
        replace = join(old_java_home, 'bin') if old_java_home else None
        if replace in path:
            path = [e if e != replace else jdk_bin for e in path]
        else:
            path.append(jdk_bin)
        print >> source, args.shell_setvar_format % ('PATH', args.shell_PATH_sep.join(path))
    source = source.getvalue().strip()

    print 'JAVA_HOME=' + jdk
    if extra_jdks:
        print 'EXTRA_JAVA_HOMES=' + os.pathsep.join(extra_jdks)
    if args.shell_source:
        with open(args.shell_source, 'w') as fp:
            print >> fp, source
    else:
        env = get_suite_env_file()
        if env:
            with open(env, 'a') as fp:
                print >> fp, 'JAVA_HOME=' + jdk
                if extra_jdks:
                    print >> fp, 'EXTRA_JAVA_HOMES=' + os.pathsep.join(extra_jdks)
            print 'Updated', env
        else:
            print
            print 'To apply the above environment variable settings, eval the following in your shell:'
            print
            print source

# main
jdk_cache_path = join(expanduser('~'), '.mx', 'jdk_cache')
if len(args.jdks) != 0:
    invalid_jdks = [a for a in args.jdks if not is_valid_jdk(a)]
    if invalid_jdks:
        raise SystemExit('Following JDKs appear to be invalid (java executable not found):\n' + '\n'.join(invalid_jdks))
    with open(jdk_cache_path, 'a') as fp:
        for jdk in args.jdks:
            print >> fp, jdk
    apply_selection(args.jdks[0], args.jdks[1:])
else:
    print "Current JDK Settings:"
    print "JAVA_HOME=%s" % os.environ.get('JAVA_HOME', '')
    print "EXTRA_JAVA_HOMES=%s" %  os.environ.get('EXTRA_JAVA_HOMES', '')
    jdks = find_system_jdks()
    if exists(jdk_cache_path):
        with open(jdk_cache_path) as fp:
            jdks.update((line.strip() for line in fp.readlines() if is_valid_jdk(line.strip())))

    choices = list(enumerate(sorted(jdks)))
    if choices:
        _, tmp_cache_path = tempfile.mkstemp(dir=dirname(jdk_cache_path))
        with open(tmp_cache_path, 'w') as fp:
            for index, jdk in choices:
                print '[{}] {}'.format(index, jdk)
                print >> fp, jdk
        os.rename(tmp_cache_path, jdk_cache_path)
        choices = {str(index):jdk for index, jdk in choices}
        jdks = [choices[n] for n in raw_input('Select JDK(s) (separate multiple choices by whitespace)> ').split() if n in choices]
        if jdks:
            apply_selection(jdks[0], jdks[1:])
