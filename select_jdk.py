#!/usr/bin/env python3
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
from __future__ import print_function

import os, tempfile, pipes
from argparse import ArgumentParser, REMAINDER
from os.path import exists, expanduser, join, isdir, isfile, realpath, dirname, abspath
from io import StringIO

def is_valid_jdk(jdk):
    """
    Determines if `jdk` looks like a valid JDK directory.

    :return: True if there's a ``java`` executable in ``jdk/bin``
    """
    java_exe = join(jdk, 'bin', 'java')
    if not exists(java_exe):
        java_exe += '.exe'
    return isfile(java_exe) and os.access(java_exe, os.X_OK)

def find_jdks_in(base_dir, jdks):
    """
    Finds JDKs in `base_dir` and adds them to `jdks`.
    """
    for n in os.listdir(base_dir):
        jdk = join(base_dir, n)
        mac_jdk = join(jdk, 'Contents', 'Home')
        if isdir(mac_jdk):
            jdk = mac_jdk
        if is_valid_jdk(jdk):
            jdks.add(realpath(jdk))

def find_system_jdks():
    """
    Returns a set of valid JDK directories by searching standard locations.
    """
    bases = [
        '/Library/Java/JavaVirtualMachines',
        '/usr/lib/jvm',
        '/usr/java',
        '/usr/jdk/instances',
        r'C:\Program Files\Java',
        join(expanduser('~'), '.mx', 'jdks') # default --to value for `mx fetch-jdk` command
    ]
    jdks = set()
    for base in bases:
        if isdir(base):
            find_jdks_in(base, jdks)
    return jdks

def get_suite_env_file(suite_dir='.'):
    for n in os.listdir(suite_dir):
        if n.startswith('mx.'):
            suite_py = join(suite_dir, n, 'suite.py')
            if exists(suite_py):
                return abspath(join(suite_dir, n, 'env'))
    return None

def get_setvar_format(shell):
    if shell == 'csh':
        return 'setenv %s %s'
    if shell == 'fish':
        return 'set -x %s %s'
    return 'export %s=%s'

def get_clearvar_format(shell):
    if shell == 'fish':
        return 'set -e %s'
    return 'unset %s'

def get_PATH_sep(shell):
    if shell == 'fish':
        return ' '
    return os.pathsep

def get_shell_commands(args, jdk, extra_jdks):
    setvar_format = get_setvar_format(args.shell)
    shell_commands = StringIO()
    print(setvar_format % ('JAVA_HOME', jdk), file=shell_commands)
    if extra_jdks:
        print(setvar_format % ('EXTRA_JAVA_HOMES', os.pathsep.join(extra_jdks)), file=shell_commands)
    else:
        print(get_clearvar_format(args.shell) % ('EXTRA_JAVA_HOMES'), file=shell_commands)
    path = os.environ.get('PATH').split(os.pathsep)
    if path:
        jdk_bin = join(jdk, 'bin')
        old_java_home = os.environ.get('JAVA_HOME')
        replace = join(old_java_home, 'bin') if old_java_home else None
        if replace in path:
            path = [e if e != replace else jdk_bin for e in path]
        else:
            path = [jdk_bin] + path
        path = [pipes.quote(e) for e in path]
        print(setvar_format % ('PATH', get_PATH_sep(args.shell).join(path)), file=shell_commands)
    return shell_commands.getvalue().strip()

_ansi_color_table = {
    'black' : '30',
    'red' : '31',
    'green' : '32',
    'yellow' : '33',
    'blue' : '34',
    'magenta' : '35',
    'cyan' : '36'
}

def colorize(msg, color):
    code = _ansi_color_table[color]
    return '\033[' + code + ';1m' + msg + '\033[0m'

def apply_selection(args, jdk, extra_jdks):
    print(colorize('JAVA_HOME=' + jdk, 'green'))
    if extra_jdks:
        print(colorize('EXTRA_JAVA_HOMES=' + os.pathsep.join(extra_jdks), 'cyan'))

    if args.shell_file:
        with open(args.shell_file, 'w') as fp:
            print(get_shell_commands(args, jdk, extra_jdks), file=fp)
    else:
        env = get_suite_env_file(args.suite_path) if args.suite_path else None
        if env:
            with open(env, 'a') as fp:
                print('JAVA_HOME=' + jdk, file=fp)
                if extra_jdks:
                    print('EXTRA_JAVA_HOMES=' + os.pathsep.join(extra_jdks), file=fp)
            print('Updated', env)
        else:
            print()
            print('To apply the above environment variable settings, eval the following in your shell:')
            print()
            print(get_shell_commands(args, jdk, extra_jdks))

if __name__ == '__main__':
    parser = ArgumentParser(prog='select_jdk', usage='%(prog)s [options] [<primary jdk> [<secondary jdk>...]]' + """
        Selects values for the JAVA_HOME, EXTRA_JAVA_HOMES and PATH environment variables based on
        the explicitly supplied JDKs or on system JDKs plus previously selected JDKs (cached in ~/.mx/jdk_cache).

        If the -s/--shell-source option is given, settings appropriate for the current shell are written to
        the given file such that it can be eval'ed in the shell to apply the settings. For example, in ~/.config/fish/config.fish:

if test -x (dirname (which mx))/select_jdk.py
    function select_jdk
        set tmp_file (mktemp)
        eval (dirname (which mx))/select_jdk.py -s $tmp_file $argv
        source $tmp_file
        rm $tmp_file
    end
end

        or in ~/.bashrc:

if [ -x $(dirname $(which mx))/select_jdk.py ]; then
    function select_jdk {
        TMP_FILE=select_jdk.$$
        eval $(dirname $(which mx))/select_jdk.py -s $TMP_FILE "$@"
        source $TMP_FILE
        rm $TMP_FILE
    }
fi

        In the absence of -s, if the current directory looks like a suite, the mx.<suite>/env file is
        created/updated with the selected values for JAVA_HOME and EXTRA_JAVA_HOMES.

        Otherwise, the settings are printed such that they can applied manually.
    """)

    shell_or_env = parser.add_mutually_exclusive_group()
    shell_or_env.add_argument('-s', '--shell-file', action='store', help='write shell commands for setting env vars to <path>', metavar='<path>')
    shell_or_env.add_argument('-p', '--suite-path', help='directory of suite whose env file is to be updated', metavar='<path>')
    parser.add_argument('--shell', action='store', help='shell syntax to use for commands', metavar='<format>', choices=['sh', 'fish', 'csh'])
    parser.add_argument('jdks', nargs=REMAINDER, metavar='<primary jdk> [<secondary jdk>...]')

    args = parser.parse_args()

    if args.shell is None:
        shell = os.environ.get('SHELL')
        if shell.endswith('fish'):
            args.shell = 'fish'
        elif shell.endswith('csh'):
            args.shell = 'csh'
        else:
            args.shell = 'sh'

    jdk_cache_path = join(expanduser('~'), '.mx', 'jdk_cache')
    if len(args.jdks) != 0:
        invalid_jdks = [a for a in args.jdks if not is_valid_jdk(a)]
        if invalid_jdks:
            raise SystemExit('Following JDKs appear to be invalid (java executable not found):\n' + '\n'.join(invalid_jdks))
        if not exists(dirname(jdk_cache_path)):
            os.makedirs(dirname(jdk_cache_path))
        with open(jdk_cache_path, 'a') as fp:
            for jdk in args.jdks:
                print(abspath(jdk), file=fp)
        apply_selection(args, abspath(args.jdks[0]), [abspath(a) for a in args.jdks[1:]])
    else:
        jdks = find_system_jdks()
        if exists(jdk_cache_path):
            with open(jdk_cache_path) as fp:
                for line in fp.readlines():
                    jdk = line.strip()
                    if is_valid_jdk(jdk):
                        jdks.add(jdk)
                        base_dir = dirname(jdk)
                        if base_dir.endswith('/Contents/Home'):
                            base_dir = base_dir[0:-len('/Contents/Home')]
                        find_jdks_in(base_dir, jdks)

        sorted_jdks = sorted(jdks)
        choices = list(enumerate(sorted_jdks))
        if choices:
            _, tmp_cache_path = tempfile.mkstemp(dir=dirname(jdk_cache_path))
            java_home = os.environ.get('JAVA_HOME', '')
            extra_java_homes = os.environ.get('EXTRA_JAVA_HOMES', '').split(os.pathsep)
            with open(tmp_cache_path, 'w') as fp:
                for index, jdk in choices:
                    if jdk == java_home:
                        print(colorize('[{}] {} {{JAVA_HOME}}'.format(index, jdk), 'green'))
                    elif jdk in extra_java_homes:
                        print(colorize('[{}] {} {{EXTRA_JAVA_HOMES[{}]}}'.format(index, jdk, extra_java_homes.index(jdk)), 'cyan'))
                    else:
                        print('[{}] {}'.format(index, jdk))
                    print(jdk, file=fp)

            os.rename(tmp_cache_path, jdk_cache_path)
            choices = {str(index):jdk for index, jdk in choices}
            jdks = [choices[n] for n in input('Select JDK(s) (separate multiple choices by whitespace)> ').split() if n in choices]
            if jdks:
                apply_selection(args, jdks[0], jdks[1:])
