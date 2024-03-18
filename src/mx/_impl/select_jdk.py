#!/usr/bin/env python3
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2024, Oracle and/or its affiliates. All rights reserved.
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

import os, tempfile, shlex, subprocess, re, sys
from argparse import ArgumentParser, REMAINDER
from os.path import exists, expanduser, join, isdir, isfile, realpath, dirname, abspath, basename, getmtime
from io import StringIO

default_jdk_cache_path = join(expanduser('~'), '.mx', 'jdk_cache')

def is_valid_jdk(jdk):
    """
    Determines if `jdk` looks like a valid JDK directory.

    :return: True if there's a ``java`` executable in ``jdk/bin``
    """
    release = join(jdk, 'release')
    java_exe = join(jdk, 'bin', 'java')
    if not exists(java_exe):
        java_exe += '.exe'
    return isfile(release) and isfile(java_exe) and os.access(java_exe, os.X_OK)

def find_jdks_in(base_dir):
    """
    Finds JDKs in `base_dir` and returns them in a set.
    """
    jdks = set()
    base_dirs = os.listdir(base_dir)
    base_dirs += [join(n, 'fastdebug') for n in base_dirs]
    for n in base_dirs:
        java_home = join(base_dir, n)
        mac_jdk = join(java_home, 'Contents', 'Home')
        if isdir(mac_jdk):
            java_home = mac_jdk
        if is_valid_jdk(java_home):
            jdks.add(realpath(java_home))
    return jdks

def find_system_jdks():
    """
    Returns a set of valid JDK directories by searching standard locations.
    """
    user_home_cache = join(expanduser('~'), '.mx', 'jdks') # default --to value for `mx fetch-jdk` command

    bases = [
        '/Library/Java/JavaVirtualMachines',
        '/usr/lib/jvm',
        '/usr/java',
        '/usr/jdk/instances',
        r'C:\Program Files\Java',
        user_home_cache,
        join(user_home_cache, 'amd64') # M1 Rosetta support
    ]
    jdks = set()
    for base in bases:
        if isdir(base):
            jdks.update(find_jdks_in(base))
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
    if shell == 'cmd':
        return 'set %s=%s'
    return 'export %s=%s'

def get_clearvar_format(shell):
    if shell == 'fish':
        return 'set -e %s'
    if shell == 'cmd':
        return 'set %s='
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
        if not sys.platform.startswith('win32'):
            # Quoting breaks the cmd shell
            path = [shlex.quote(e) for e in path]
        print(setvar_format % ('PATH', get_PATH_sep(args.shell).join(path)), file=shell_commands)
    return shell_commands.getvalue().strip()

_ansi_color_table = {
    # duplicates support/logging.py
    'black' : '30',
    'red' : '31',
    'green' : '32',
    'yellow' : '33',
    'blue' : '34',
    'magenta' : '35',
    'cyan' : '36'
}

def colorize(msg, color):
    if sys.platform.startswith('win32'):
        # Colorization does not seem to work in cmd shell
        return msg
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

class JDKInfo(object):
    def __init__(self, java_home, java_specification_version, java_version, java_vm_version):
        self.java_home = java_home
        self.java_specification_version = java_specification_version
        self.java_version = java_version
        self.java_vm_version = java_vm_version
        self.name = JDKInfo.init_name(java_home)

    JAVA_PROP_RE = re.compile(r'\s+(java\.[\w\.]+) = (.*)')
    VENDOR_RE = re.compile(r'([A-Za-z]+).*')

    @staticmethod
    def release_timestamp(java_home):
        release = join(java_home, 'release')
        return str(getmtime(release))

    @staticmethod
    def init_name(java_home):
        jdk_dir = java_home
        if jdk_dir.endswith('/Contents/Home'):
            jdk_dir = jdk_dir[:-len('/Contents/Home')]
        base = basename(jdk_dir)
        if base in ('debug', 'fastdebug', 'slowdebug'):
            base = basename(dirname(jdk_dir))
        m = JDKInfo.VENDOR_RE.fullmatch(base)
        name = m.group(1) if m else base
        if 'debug' in base and 'debug' not in name:
            name += '-debug'
        return name

    @staticmethod
    def extract_java_prop(line, props):
        m = JDKInfo.JAVA_PROP_RE.fullmatch(line)
        if m:
            props[m.group(1)] = m.group(2)

    @staticmethod
    def for_java_home(java_home):
        java_exe = join(java_home, 'bin', 'java')
        if not exists(java_exe):
            java_exe += '.exe'
        p = subprocess.run([java_exe, '-XshowSettings:properties', '-version'], capture_output=True, text=True, check=True)
        props = {}
        for line in p.stderr.split('\n'):
            JDKInfo.extract_java_prop(line, props)
        java_specification_version = props['java.specification.version']
        java_version = props['java.version']
        java_vm_version = props['java.vm.version']
        return JDKInfo(java_home, java_specification_version, java_version, java_vm_version)

    @staticmethod
    def load_from_jdk_cache(line, jdk_cache_path, line_num):
        parts = line.strip().split('|')
        java_home = parts[0]
        if not is_valid_jdk(java_home):
            return None
        if len(parts) != 5:
            return None
        java_specification_version, java_version, java_vm_version, expect_timestamp = parts[1:]
        actual_timestamp = JDKInfo.release_timestamp(java_home)
        if expect_timestamp != actual_timestamp:
            return None
        return JDKInfo(java_home, java_specification_version, java_version, java_vm_version)

    def as_jdk_cache_line(self):
        timestamp = JDKInfo.release_timestamp(self.java_home)
        return f'{self.java_home}|{self.java_specification_version}|{self.java_version}|{self.java_vm_version}|{timestamp}'

    def sort_key(self):
        return (self.name, self.java_specification_version, self.java_vm_version, self.java_home)

    def __lt__(self, other):
        return self.sort_key() < other.sort_key()

def choose_jdks(jdk_cache_path=default_jdk_cache_path, only_list=False):
    jdks = {}
    if exists(jdk_cache_path):
        with open(jdk_cache_path) as fp:
            line_num = 1
            for line in fp.readlines():
                jdk = JDKInfo.load_from_jdk_cache(line.strip(), jdk_cache_path, line_num)
                line_num += 1
                if jdk:
                    jdks[jdk.java_home] = jdk
                    base_dir = dirname(jdk.java_home)
                    if base_dir.endswith('/Contents/Home'):
                        base_dir = base_dir[0:-len('/Contents/Home')]
                    for java_home in find_jdks_in(base_dir):
                        if java_home not in jdks:
                            jdks[java_home] = JDKInfo.for_java_home(java_home)
    for java_home in find_system_jdks():
        if java_home not in jdks:
            jdks[java_home] = JDKInfo.for_java_home(java_home)

    sorted_jdks = sorted(jdks.values())
    choices = list(enumerate(sorted_jdks))
    col2_width = max(((len(jdk.name + '-' + jdk.java_specification_version)) for jdk in sorted_jdks)) + 1
    col3_width = max(((len(jdk.java_vm_version)) for jdk in sorted_jdks)) + 1
    if choices:
        tmp_cache_path_fd, tmp_cache_path = tempfile.mkstemp(dir=dirname(jdk_cache_path))
        # Windows will complain about tmp_cache_path being in use by another process
        # when calling os.rename if we don't close the file descriptor.
        os.close(tmp_cache_path_fd)

        java_home = os.environ.get('JAVA_HOME', '')
        extra_java_homes = os.environ.get('EXTRA_JAVA_HOMES', '').split(os.pathsep)
        with open(tmp_cache_path, 'w') as fp:
            for index, jdk in choices:
                col1 = f'[{index}]'
                col2 = f'{jdk.name}-{jdk.java_specification_version}'
                col3 = jdk.java_vm_version
                col4 = jdk.java_home
                if only_list:
                    print(f'{col2:{col2_width}} {col3:{col3_width}} {col4}')
                else:
                    line = f'{col1:>5} {col2:{col2_width}} {col3:{col3_width}} {col4}'
                    if jdk.java_home == java_home:
                        line = colorize(f'{line} {{JAVA_HOME}}', 'green')
                    elif jdk.java_home in extra_java_homes:
                        line = colorize(f'{line} {{EXTRA_JAVA_HOMES[{extra_java_homes.index(jdk.java_home)}]}}', 'cyan')
                    print(line)
                    print(f'{jdk.as_jdk_cache_line()}', file=fp)
        if only_list:
            os.unlink(tmp_cache_path)
        else:
            os.rename(tmp_cache_path, jdk_cache_path)
            choices = {str(index):jdk for index, jdk in choices}
            jdks = [choices[n] for n in input('Select JDK(s) (separate multiple choices by whitespace)> ').split() if n in choices]
            if jdks:
                return jdks

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
    parser.add_argument('--list', action='store_true', help='list the available JDKs without selecting any')
    parser.add_argument('jdks', nargs=REMAINDER, metavar='<primary jdk> [<secondary jdk>...]')

    args = parser.parse_args()

    if args.shell is None:
        shell = os.environ.get('SHELL', '')
        if shell.endswith('fish'):
            args.shell = 'fish'
        elif shell.endswith('csh'):
            args.shell = 'csh'
        elif os.environ.get('COMSPEC', '').endswith('cmd.exe'):
            args.shell = 'cmd'
        else:
            args.shell = 'sh'

    jdk_cache_path = default_jdk_cache_path
    if len(args.jdks) != 0:
        if args.list:
            print('warning: ignore --list option since JDKs were specified on the command line')
        invalid_jdks = [a for a in args.jdks if not is_valid_jdk(a)]
        if invalid_jdks:
            raise SystemExit('Following JDKs appear to be invalid (java executable not found):\n' + '\n'.join(invalid_jdks))
        if not exists(dirname(jdk_cache_path)):
            os.makedirs(dirname(jdk_cache_path))
        with open(jdk_cache_path, 'a') as fp:
            for java_home in args.jdks:
                jdk = JDKInfo.for_java_home(abspath(java_home))
                if jdk:
                    print(f'{jdk.as_jdk_cache_line()}', file=fp)
        apply_selection(args, abspath(args.jdks[0]), [abspath(a) for a in args.jdks[1:]])
    else:
        jdks = choose_jdks(jdk_cache_path, args.list)
        if jdks:
            apply_selection(args, jdks[0].java_home, [jdk.java_home for jdk in jdks[1:]])
