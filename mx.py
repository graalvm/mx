#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2019, Oracle and/or its affiliates. All rights reserved.
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
r"""
mx is a command line tool for managing the development of Java code organized as suites of projects.

"""
from __future__ import print_function

import sys

if sys.version_info < (2, 7):
    major, minor, micro, _, _ = sys.version_info
    raise SystemExit('mx requires python 2.7+, not {0}.{1}.{2}'.format(major, minor, micro))

from abc import ABCMeta, abstractmethod

if __name__ == '__main__':
    # Rename this module as 'mx' so it is not re-executed when imported by other modules.
    sys.modules['mx'] = sys.modules.pop('__main__')

try:
    import defusedxml #pylint: disable=unused-import
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse
import os, errno, time, subprocess, shlex, zipfile, signal, tempfile, platform
import textwrap
import socket
import tarfile, gzip
import hashlib
import itertools
from functools import cmp_to_key
# TODO use defusedexpat?
import xml.parsers.expat, xml.sax.saxutils, xml.dom.minidom
from xml.dom.minidom import parseString as minidomParseString
import shutil, re
import pipes
import difflib
import glob
import filecmp
import json
from collections import OrderedDict, namedtuple, deque
from datetime import datetime
from threading import Thread
from argparse import ArgumentParser, REMAINDER, Namespace, FileType, HelpFormatter, ArgumentTypeError, RawTextHelpFormatter
from os.path import join, basename, dirname, exists, lexists, isabs, expandvars, isdir, islink, normpath, realpath
from tempfile import mkdtemp, mkstemp
import fnmatch
import operator
import calendar
import multiprocessing
from stat import S_IMODE, S_IWRITE
from mx_commands import MxCommands, MxCommand
_mx_commands = MxCommands("mx")

# Temporary imports and (re)definitions while porting mx from Python 2 to Python 3
if sys.version_info[0] < 3:
    filter = itertools.ifilter                 # pylint: disable=redefined-builtin,invalid-name
    def input(prompt=None):                    # pylint: disable=redefined-builtin
        return raw_input(prompt)               # pylint: disable=undefined-variable

    from StringIO import StringIO
    import __builtin__ as builtins
    import urllib2                             # pylint: disable=unused-import
    _urllib_request = urllib2
    _urllib_error = urllib2
    del urllib2
    import urlparse as _urllib_parse
    def _decode(x):
        return x
    def _encode(x):
        return x
    _unicode = unicode                         # pylint: disable=undefined-variable
else:
    from io import StringIO
    import builtins                            # pylint: disable=unused-import,no-name-in-module
    import urllib.request as _urllib_request   # pylint: disable=unused-import,no-name-in-module
    import urllib.error as _urllib_error       # pylint: disable=unused-import,no-name-in-module
    import urllib.parse as _urllib_parse       # pylint: disable=unused-import,no-name-in-module
    def _decode(x):
        return x.decode()
    def _encode(x):
        return x.encode()
    _unicode = str

### ~~~~~~~~~~~~~ _private

def _hashFromUrl(url):
    logvv('Retrieving SHA1 from {}'.format(url))
    hashFile = _urllib_request.urlopen(url)
    try:
        return hashFile.read()
    except _urllib_error.URLError as e:
        _suggest_http_proxy_error(e)
        abort('Error while retrieving sha1 {}: {}'.format(url, str(e)))
    finally:
        if hashFile:
            hashFile.close()

def _merge_file_contents(input_files, output_file):
    for file_name in input_files:
        with open(file_name, 'r') as input_file:
            shutil.copyfileobj(input_file, output_file)
        output_file.flush()

def _make_absolute(path, prefix):
    """
    If 'path' is not absolute prefix it with 'prefix'
    """
    return join(prefix, path)


def _cache_dir():
    return _cygpathW2U(get_env('MX_CACHE_DIR', join(dot_mx_dir(), 'cache')))


def _get_path_in_cache(name, sha1, urls, ext=None, sources=False, oldPath=False):
    """
    Gets the path an artifact has (or would have) in the download cache.
    """
    assert sha1 != 'NOCHECK', 'artifact for ' + name + ' cannot be cached since its sha1 is NOCHECK'
    if ext is None:
        for url in urls:
            # Use extension of first URL whose path component ends with a non-empty extension
            o = _urllib_parse.urlparse(url)
            if o.path == "/remotecontent" and o.query.startswith("filepath"):
                path = o.query
            else:
                path = o.path
            ext = get_file_extension(path)
            if ext:
                ext = '.' + ext
                break
        if not ext:
            abort('Could not determine a file extension from URL(s):\n  ' + '\n  '.join(urls))
    assert os.sep not in name, name + ' cannot contain ' + os.sep
    assert os.pathsep not in name, name + ' cannot contain ' + os.pathsep
    if oldPath:
        return join(_cache_dir(), name + ('.sources' if sources else '') + '_' + sha1 + ext)  # mx < 5.176.0
    filename = _map_to_maven_dist_name(name) + ('.sources' if sources else '') + ext
    return join(_cache_dir(), name + '_' + sha1 + ('.dir' if not ext else ''), filename)


def _urlopen(*args, **kwargs):
    timeout_attempts = [0]
    timeout_retries = kwargs.pop('timeout_retries', 3)

    def on_timeout():
        if timeout_attempts[0] <= timeout_retries:
            timeout_attempts[0] += 1
            kwargs['timeout'] = kwargs.get('timeout', 5) * 2
            warn("urlopen() timed out! Retrying with timeout of {}s.".format(kwargs['timeout']))
            return True
        return False

    error500_attempts = 0
    error500_limit = 5

    while True:
        try:
            return _urllib_request.urlopen(*args, **kwargs)
        except (_urllib_error.HTTPError) as e:
            if e.code == 500:
                if error500_attempts < error500_limit:
                    error500_attempts += 1
                    url = '?' if len(args) == 0 else args[0]
                    warn("Retrying after error reading from " + url + ": " + str(e))
                    time.sleep(0.2)
                    continue
            raise
        except _urllib_error.URLError as e:
            if isinstance(e.reason, socket.error):
                if e.reason.errno == errno.EINTR and 'timeout' in kwargs and is_interactive():
                    warn("urlopen() failed with EINTR. Retrying without timeout.")
                    del kwargs['timeout']
                    return _urllib_request.urlopen(*args, **kwargs)
                if e.reason.errno == errno.EINPROGRESS:
                    if on_timeout():
                        continue
            if isinstance(e.reason, socket.timeout):
                if on_timeout():
                    continue
            raise
        except socket.timeout:
            if on_timeout():
                continue
            raise
        abort("should not reach here")


def _check_file_with_sha1(path, sha1, sha1path, mustExist=True, newFile=False, logErrors=False):
    """
    Checks if a file exists and is up to date according to the sha1.
    Returns False if the file is not there or does not have the right checksum.
    """
    sha1Check = sha1 and sha1 != 'NOCHECK'

    def _sha1CachedValid():
        if not exists(sha1path):
            return False
        if TimeStampFile(path, followSymlinks=True).isNewerThan(sha1path):
            return False
        return True

    def _sha1Cached():
        with open(sha1path, 'r') as f:
            return f.read()[0:40]

    def _writeSha1Cached(value=None):
        with SafeFileCreation(sha1path) as sfc, open(sfc.tmpPath, 'w') as f:
            f.write(value or sha1OfFile(path))

    if exists(path):
        if sha1Check and sha1:
            if not _sha1CachedValid() or (newFile and sha1 != _sha1Cached()):
                logv('Create/update SHA1 cache file ' + sha1path)
                _writeSha1Cached()

            if sha1 != _sha1Cached():
                computedSha1 = sha1OfFile(path)
                if sha1 == computedSha1:
                    warn('Fixing corrupt SHA1 cache file ' + sha1path)
                    _writeSha1Cached(computedSha1)
                    return True
                if logErrors:
                    size = os.path.getsize(path)
                    log_error('SHA1 of {} [size: {}] ({}) does not match expected value ({})'.format(TimeStampFile(path), size, computedSha1, sha1))
                return False
    elif mustExist:
        if logErrors:
            log_error("'{}' does not exist".format(path))
        return False

    return True


def _needsUpdate(newestInput, path):
    """
    Determines if the file denoted by `path` does not exist or `newestInput` is not None
    and `path`'s latest modification time is older than the `newestInput` TimeStampFile.
    Returns a string describing why `path` needs updating or None if it does not need updating.
    """
    if not exists(path):
        return path + ' does not exist'
    if newestInput:
        ts = TimeStampFile(path, followSymlinks=False)
        if ts.isOlderThan(newestInput):
            return '{} is older than {}'.format(ts, newestInput)
    return None

def _function_code(f):
    if hasattr(f, 'func_code'):
        # Python 2
        return f.func_code
    # Python 3
    return f.__code__

def _check_output_str(*args, **kwargs):
    return _decode(subprocess.check_output(*args, **kwargs))

def _validate_abolute_url(urlstr, acceptNone=False):
    if urlstr is None:
        return acceptNone
    url = _urllib_parse.urlsplit(urlstr)
    return url.scheme and (url.netloc or url.path)

def _safe_path(path):
    """
    If not on Windows, this function returns `path`.
    Otherwise, it return a potentially transformed path that is safe for file operations.
    This works around the MAX_PATH limit on Windows:
    https://msdn.microsoft.com/en-us/library/windows/desktop/aa365247(v=vs.85).aspx#maxpath
    """
    if is_windows():
        if _opts.verbose and '/' in path:
            warn("Forward slash in path on windows: {}".format(path))
            import traceback
            traceback.print_stack()
        path = normpath(path)
        if isabs(path):
            if path.startswith('\\\\'):
                if path[2:].startswith('?\\'):
                    # if it already has a \\?\ don't do the prefix
                    pass
                else:
                    # only a UNC path has a double slash prefix
                    path = '\\\\?\\UNC' + path
            else:
                path = '\\\\?\\' + path
        path = _unicode(path)
    return path

### ~~~~~~~~~~~~~ command

def command_function(name, fatalIfMissing=True):
    """
    Return the function for the (possibly overridden) command named `name`.
    If no such command, abort if `fatalIsMissing` is True, else return None
    """
    return _mx_commands.command_function(name, fatalIfMissing)


def update_commands(suite, new_commands):
    """
    Using the decorator mx_command is preferred over this function.

    :param suite: for which the command is added.
    :param new_commands: keys are command names, value are lists: [<function>, <usage msg>, <format doc function>]
        if any of the format args are instances of callable, then they are called with an 'env' are before being
        used in the call to str.format().
    """
    suite_name = suite if isinstance(suite, str) else suite.name

    _length_of_command = 4
    for command_name, command_list in new_commands.items():
        assert len(command_list) > 0 and command_list[0] is not None
        args = [suite_name, command_name] + command_list[1:_length_of_command]
        command_decorator = command(*args)
        # apply the decorator so all functions are tracked
        command_list[0] = command_decorator(command_list[0])


def command(suite_name, command_name, usage_msg='', doc_function=None, props=None, auto_add=True):
    """
    Decorator for making a function an mx shell command.

    The annotated function should have a single parameter typed List[String].

    :param suite_name: suite to which the command belongs to.
    :param command_name: the command name. Will be used in the shell command.
    :param usage_msg: message to display usage.
    :param doc_function: function to render the documentation for this feature.
    :param props: a dictionary of properties attributed to this command.
    :param auto_add: automatically it to the commands.
    :return: the decorator factory for the function.
    """
    def mx_command_decorator_factory(command_func):
        mx_command = MxCommand(_mx_commands, command_func, suite_name, command_name, usage_msg, doc_function, props)
        if auto_add:
            _mx_commands.add_commands([mx_command])
        return mx_command

    return mx_command_decorator_factory

### ~~~~~~~~~~~~~ Language support

# Support for comparing objects given removal of `cmp` function in Python 3.
# https://portingguide.readthedocs.io/en/latest/comparisons.html
def compare(a, b):
    return (a > b) - (a < b)

class Comparable(object):
    def _checked_cmp(self, other, f):
        compar = self.__cmp__(other) #pylint: disable=assignment-from-no-return
        return f(compar, 0) if compar is not NotImplemented else compare(id(self), id(other))

    def __lt__(self, other):
        return self._checked_cmp(other, lambda a, b: a < b)
    def __gt__(self, other):
        return self._checked_cmp(other, lambda a, b: a > b)
    def __eq__(self, other):
        return self._checked_cmp(other, lambda a, b: a == b)
    def __le__(self, other):
        return self._checked_cmp(other, lambda a, b: a <= b)
    def __ge__(self, other):
        return self._checked_cmp(other, lambda a, b: a >= b)
    def __ne__(self, other):
        return self._checked_cmp(other, lambda a, b: a != b)

    def __cmp__(self, other): # to override
        raise TypeError("No override for compare")

class DynamicVar(object):
    def __init__(self, initial_value):
        self.value = initial_value

    def get(self):
        return self.value

    def set_scoped(self, newvalue):
        return DynamicVarScope(self, newvalue)


class DynamicVarScope(object):
    def __init__(self, dynvar, newvalue):
        self.dynvar = dynvar
        self.newvalue = newvalue

    def __enter__(self):
        assert not hasattr(self, "oldvalue")
        self.oldvalue = self.dynvar.value
        self.dynvar.value = self.newvalue

    def __exit__(self, tpe, value, traceback):
        self.dynvar.value = self.oldvalue
        self.oldvalue = None
        self.newvalue = None


class ArgParser(ArgumentParser):
    # Override parent to append the list of available commands
    def format_help(self):
        return ArgumentParser.format_help(self) + """
environment variables:
  JAVA_HOME             Default value for primary JDK directory. Can be overridden with --java-home option.
  EXTRA_JAVA_HOMES      Secondary JDK directories. Can be overridden with --extra-java-homes option.
  MX_ALT_OUTPUT_ROOT    Alternate directory for generated content. Instead of <suite>/mxbuild, generated
                        content will be placed under $MX_ALT_OUTPUT_ROOT/<suite>. A suite can override
                        this with the suite level "outputRoot" attribute in suite.py.
  MX_GIT_CACHE          Use a cache for git objects during clones.
                         * Setting it to `reference` will clone repositories using the cache and let them
                           reference the cache (if the cache gets deleted these repositories will be
                           incomplete).
                         * Setting it to `dissociated` will clone using the cache but then dissociate the
                           repository from the cache.
                         * Setting it to `refcache` will synchronize with server only if a branch is
                           requested or if a specific revision is requested which does not exist in the
                           local cache. Hence, remote references will be synchronized occasionally. This
                           allows cloning without even contacting the git server.
                        The cache is located at `~/.mx/git-cache`.
""" + _format_commands()


    def __init__(self, parents=None):
        self.parsed = False
        if not parents:
            parents = []
        ArgumentParser.__init__(self, prog='mx', parents=parents, add_help=len(parents) != 0, formatter_class=lambda prog: HelpFormatter(prog, max_help_position=32, width=120))

        if len(parents) != 0:
            # Arguments are inherited from the parents
            return

        self.add_argument('-v', action='store_true', dest='verbose', help='enable verbose output')
        self.add_argument('-V', action='store_true', dest='very_verbose', help='enable very verbose output')
        self.add_argument('--no-warning', action='store_false', dest='warn', help='disable warning messages')
        self.add_argument('--quiet', action='store_true', help='disable log messages')
        self.add_argument('-y', action='store_const', const='y', dest='answer', help='answer \'y\' to all questions asked')
        self.add_argument('-n', action='store_const', const='n', dest='answer', help='answer \'n\' to all questions asked')
        self.add_argument('-p', '--primary-suite-path', help='set the primary suite directory', metavar='<path>')
        self.add_argument('--dbg', type=int, dest='java_dbg_port', help='make Java processes wait on <port> for a debugger', metavar='<port>')
        self.add_argument('-d', action='store_const', const=8000, dest='java_dbg_port', help='alias for "-dbg 8000"')
        self.add_argument('--attach', dest='attach', help='Connect to existing server running at [<address>:]<port>')
        self.add_argument('--backup-modified', action='store_true', help='backup generated files if they pre-existed and are modified')
        self.add_argument('--cp-pfx', dest='cp_prefix', help='class path prefix', metavar='<arg>')
        self.add_argument('--cp-sfx', dest='cp_suffix', help='class path suffix', metavar='<arg>')
        jargs = self.add_mutually_exclusive_group()
        jargs.add_argument('-J', dest='java_args', help='Java VM arguments (e.g. "-J-dsa")', metavar='<arg>')
        jargs.add_argument('--J', dest='java_args_legacy', help='Java VM arguments (e.g. "--J @-dsa")', metavar='@<args>')
        jpargs = self.add_mutually_exclusive_group()
        jpargs.add_argument('-P', action='append', dest='java_args_pfx', help='prefix Java VM arguments (e.g. "-P-dsa")', metavar='<arg>', default=[])
        jpargs.add_argument('--Jp', action='append', dest='java_args_pfx_legacy', help='prefix Java VM arguments (e.g. --Jp @-dsa)', metavar='@<args>', default=[])
        jaargs = self.add_mutually_exclusive_group()
        jaargs.add_argument('-A', action='append', dest='java_args_sfx', help='suffix Java VM arguments (e.g. "-A-dsa")', metavar='<arg>', default=[])
        jaargs.add_argument('--Ja', action='append', dest='java_args_sfx_legacy', help='suffix Java VM arguments (e.g. --Ja @-dsa)', metavar='@<args>', default=[])
        self.add_argument('--user-home', help='users home directory', metavar='<path>', default=os.path.expanduser('~'))
        self.add_argument('--java-home', help='primary JDK directory (must be JDK 7 or later)', metavar='<path>')
        self.add_argument('--jacoco', help='instruments selected classes using JaCoCo', default='off', choices=['off', 'on', 'append'])
        self.add_argument('--jacoco-whitelist-package', help='only include classes in the specified package', metavar='<package>', action='append', default=[])
        self.add_argument('--jacoco-exclude-annotation', help='exclude classes with annotation from JaCoCo instrumentation', metavar='<annotation>', action='append', default=[])
        self.add_argument('--extra-java-homes', help='secondary JDK directories separated by "' + os.pathsep + '"', metavar='<path>')
        self.add_argument('--strict-compliance', action='store_true', dest='strict_compliance', help='use JDK matching a project\'s Java compliance when compiling (legacy - this is the only supported mode)', default=True)
        self.add_argument('--ignore-project', action='append', dest='ignored_projects', help='name of project to ignore', metavar='<name>', default=[])
        self.add_argument('--kill-with-sigquit', action='store_true', dest='killwithsigquit', help='send sigquit first before killing child processes')
        self.add_argument('--suite', action='append', dest='specific_suites', help='limit command to the given suite', metavar='<name>', default=[])
        self.add_argument('--suitemodel', help='mechanism for locating imported suites', metavar='<arg>')
        self.add_argument('--primary', action='store_true', help='limit command to primary suite')
        self.add_argument('--dynamicimports', action='append', dest='dynamic_imports', help='dynamically import suite <name>', metavar='<name>', default=[])
        self.add_argument('--no-download-progress', action='store_true', help='disable download progress meter')
        self.add_argument('--version', action='store_true', help='print version and exit')
        self.add_argument('--mx-tests', action='store_true', help='load mxtests suite (mx debugging)')
        self.add_argument('--jdk', action='store', help='JDK to use for the "java" command', metavar='<tag:compliance>')
        self.add_argument('--version-conflict-resolution', dest='version_conflict_resolution', action='store', help='resolution mechanism used when a suite is imported with different versions', default='suite', choices=['suite', 'none', 'latest', 'latest_all', 'ignore'])
        self.add_argument('-c', '--max-cpus', action='store', type=int, dest='cpu_count', help='the maximum number of cpus to use during build', metavar='<cpus>', default=None)
        self.add_argument('--strip-jars', action='store_true', help='produce and use stripped jars in all mx commands.')
        self.add_argument('--env', dest='additional_env', help='load an additional env file in the mx dir of the primary suite', metavar='<name>')

        if not is_windows():
            # Time outs are (currently) implemented with Unix specific functionality
            self.add_argument('--timeout', help='timeout (in seconds) for command', type=int, default=0, metavar='<secs>')
            self.add_argument('--ptimeout', help='timeout (in seconds) for subprocesses', type=int, default=0, metavar='<secs>')

    def _parse_cmd_line(self, opts, firstParse):
        if firstParse:

            parser = ArgParser(parents=[self])
            parser.add_argument('initialCommandAndArgs', nargs=REMAINDER, metavar='command args...')

            # Legacy support - these options are recognized during first parse and
            # appended to the unknown options to be reparsed in the second parse
            parser.add_argument('--vm', action='store', dest='vm', help='the VM type to build/run')
            parser.add_argument('--vmbuild', action='store', dest='vmbuild', help='the VM build to build/run')

            # Parse the known mx global options and preserve the unknown args, command and
            # command args for the second parse.
            _, self.unknown = parser.parse_known_args(namespace=opts)

            for deferrable in _opts_parsed_deferrables:
                deferrable()

            if opts.version:
                print('mx version ' + str(version))
                sys.exit(0)

            if opts.vm: self.unknown += ['--vm=' + opts.vm]
            if opts.vmbuild: self.unknown += ['--vmbuild=' + opts.vmbuild]

            self.initialCommandAndArgs = opts.__dict__.pop('initialCommandAndArgs')

            # For some reason, argparse considers an unknown argument starting with '-'
            # and containing a space as a positional argument instead of an optional
            # argument. We need to treat these as unknown optional arguments.
            while len(self.initialCommandAndArgs) > 0:
                arg = self.initialCommandAndArgs[0]
                if arg.startswith('-'):
                    assert ' ' in arg, arg
                    self.unknown.append(arg)
                    del self.initialCommandAndArgs[0]
                else:
                    break

            # Give the timeout options a default value to avoid the need for hasattr() tests
            opts.__dict__.setdefault('timeout', 0)
            opts.__dict__.setdefault('ptimeout', 0)

            if opts.java_args_legacy:
                opts.java_args = opts.java_args_legacy.lstrip('@')
            if opts.java_args_pfx_legacy:
                opts.java_args_pfx = [s.lstrip('@') for s in opts.java_args_pfx_legacy]
            if opts.java_args_sfx_legacy:
                opts.java_args_sfx = [s.lstrip('@') for s in opts.java_args_sfx_legacy]

            if opts.very_verbose:
                opts.verbose = True

            if opts.user_home is None or opts.user_home == '':
                abort('Could not find user home. Use --user-home option or ensure HOME environment variable is set.')

            if opts.primary and primary_suite():
                opts.specific_suites.append(primary_suite().name)

            if opts.java_home is not None:
                os.environ['JAVA_HOME'] = opts.java_home
            if opts.extra_java_homes is not None:
                os.environ['EXTRA_JAVA_HOMES'] = opts.extra_java_homes
            os.environ['HOME'] = opts.user_home

            global _primary_suite_path
            _primary_suite_path = opts.primary_suite_path or os.environ.get('MX_PRIMARY_SUITE_PATH')
            if _primary_suite_path:
                _primary_suite_path = os.path.abspath(_primary_suite_path)

            global _suitemodel
            _suitemodel = SuiteModel.create_suitemodel(opts)

            # Communicate primary suite path to mx subprocesses
            if _primary_suite_path:
                os.environ['MX_PRIMARY_SUITE_PATH'] = _primary_suite_path

            opts.ignored_projects += os.environ.get('IGNORED_PROJECTS', '').split(',')

            mx_gate._jacoco = opts.jacoco
            mx_gate._jacoco_whitelisted_packages.extend(opts.jacoco_whitelist_package)
            mx_gate.add_jacoco_excluded_annotations(opts.jacoco_exclude_annotation)
            mx_gate.Task.verbose = opts.verbose
        else:
            parser = ArgParser(parents=[self])
            parser.add_argument('commandAndArgs', nargs=REMAINDER, metavar='command args...')
            args = self.unknown + self.initialCommandAndArgs
            parser.parse_args(args=args, namespace=opts)
            commandAndArgs = opts.__dict__.pop('commandAndArgs')
            if self.initialCommandAndArgs != commandAndArgs:
                abort('Suite specific global options must use name=value format: {0}={1}'.format(self.unknown[-1], self.initialCommandAndArgs[0]))
            self.parsed = True
            return commandAndArgs


def add_argument(*args, **kwargs):
    """
    Defines a single command-line argument.
    """
    assert _argParser is not None
    _argParser.add_argument(*args, **kwargs)

def remove_doubledash(args):
    if '--' in args:
        args.remove('--')

def ask_question(question, options, default=None, answer=None):
    """"""
    assert not default or default in options
    questionMark = '? ' + options + ': '
    if default:
        questionMark = questionMark.replace(default, default.upper())
    if answer:
        answer = str(answer)
        print(question + questionMark + answer)
    else:
        if is_interactive():
            answer = input(question + questionMark) or default
            while not answer:
                answer = input(question + questionMark)
        else:
            if default:
                answer = default
            else:
                abort("Can not answer '" + question + "?' if stdin is not a tty")
    return answer.lower()

def ask_yes_no(question, default=None):
    """"""
    return ask_question(question, '[yn]', default, _opts.answer).startswith('y')

def warn(msg, context=None):
    if _opts.warn:
        if context is not None:
            if callable(context):
                contextMsg = context()
            elif hasattr(context, '__abort_context__'):
                contextMsg = context.__abort_context__()
            else:
                contextMsg = str(context)
            msg = contextMsg + ":\n" + msg
        print(colorize('WARNING: ' + msg, color='magenta', bright=True, stream=sys.stderr), file=sys.stderr)

"""
A simple timing facility.
"""
class Timer():
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        self.start = time.time()
        return self
    def __exit__(self, t, value, traceback):
        elapsed = time.time() - self.start
        print('{} took {} seconds'.format(self.name, elapsed))

def glob_match_any(patterns, path):
    return any((glob_match(pattern, path) for pattern in patterns))


def glob_match(pattern, path):
    """
    Matches a path against a pattern using glob's special rules. In particular, the pattern is checked for each part
    of the path and files starting with `.` are not matched unless the pattern also starts with a `.`.
    :param str pattern: The pattern to match with glob syntax
    :param str path: The path to be checked against the pattern
    :return: The part of the path that matches or None if the path does not match
    """
    pattern_parts = pattern.replace(os.path.sep, '/').split('/')
    path_parts = path.replace(os.path.sep, '/').split('/')
    if len(path_parts) < len(pattern_parts):
        return None
    for pattern_part, path_part in zip(pattern_parts, path_parts):
        if len(pattern_part) > 0 and pattern_part[0] != '.' and len(path_part) > 0 and path_part[0] == '.':
            return None
        if not fnmatch.fnmatch(path_part, pattern_part):
            return None
    return '/'.join(path_parts[:len(pattern_parts)])

### ~~~~~~~~~~~~~ Suite

# Define this machinery early in case other modules want to use them

# Names of commands that don't need a primary suite.
# This cannot be used outside of mx because of implementation restrictions

currently_loading_suite = DynamicVar(None)

_suite_context_free = ['init', 'version', 'urlrewrite']


def suite_context_free(func):
    """
    Decorator for commands that don't need a primary suite.
    """
    _suite_context_free.append(func.__name__)
    return func

# Names of commands that don't need a primary suite but will use one if it can be found.
# This cannot be used outside of mx because of implementation restrictions
_optional_suite_context = ['help']


def optional_suite_context(func):
    """
    Decorator for commands that don't need a primary suite but will use one if it can be found.
    """
    _optional_suite_context.append(func.__name__)
    return func

# Names of commands that need a primary suite but don't need suites to be loaded.
# This cannot be used outside of mx because of implementation restrictions
_no_suite_loading = []


def no_suite_loading(func):
    """
    Decorator for commands that need a primary suite but don't need suites to be loaded.
    """
    _no_suite_loading.append(func.__name__)
    return func

# Names of commands that need a primary suite but don't need suites to be discovered.
# This cannot be used outside of mx because of implementation restrictions
_no_suite_discovery = []


def no_suite_discovery(func):
    """
    Decorator for commands that need a primary suite but don't need suites to be discovered.
    """
    _no_suite_discovery.append(func.__name__)
    return func


class SuiteModel:
    """
    Defines how to locate a URL/path for a suite, including imported suites.
    Conceptually a SuiteModel is defined a primary suite URL/path,
    and a map from suite name to URL/path for imported suites.
    Subclasses define a specfic implementation.
    """
    def __init__(self):
        self.primaryDir = None
        self.suitenamemap = {}

    def find_suite_dir(self, suite_import):
        """locates the URL/path for suite_import or None if not found"""
        abort('find_suite_dir not implemented')

    def set_primary_dir(self, d):
        """informs that d is the primary suite directory"""
        self._primaryDir = d

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        """
        returns the directory path for an import of suite_import.name, given importer_dir.
        For a "src" suite model, if check_alternate == True and if suite_import specifies an alternate URL,
        check whether path exists and if not, return the alternate.
        """
        abort('importee_dir not implemented')

    def nestedsuites_dirname(self):
        """Returns the dirname that contains any nested suites if the model supports that"""
        return None

    def _search_dir(self, searchDir, suite_import):
        if suite_import.suite_dir:
            sd = _is_suite_dir(suite_import.suite_dir, _mxDirName(suite_import.name))
            assert sd
            return sd

        if not exists(searchDir):
            return None

        found = []
        for dd in os.listdir(searchDir):
            if suite_import.in_subdir:
                candidate = join(searchDir, dd, suite_import.name)
            else:
                candidate = join(searchDir, dd)
            sd = _is_suite_dir(candidate, _mxDirName(suite_import.name))
            if sd is not None:
                found.append(sd)

        if len(found) == 0:
            return None
        elif len(found) == 1:
            return found[0]
        else:
            abort("Multiple suites match the import {}:\n{}".format(suite_import.name, "\n".join(found)))

    def verify_imports(self, suites, args):
        """Ensure that the imports are consistent."""

    def _check_exists(self, suite_import, path, check_alternate=True):
        if check_alternate and suite_import.urlinfos is not None and not exists(path):
            return suite_import.urlinfos
        return path

    @staticmethod
    def create_suitemodel(opts):
        envKey = 'MX__SUITEMODEL'
        default = os.environ.get(envKey, 'sibling')
        name = getattr(opts, 'suitemodel') or default

        # Communicate the suite model to mx subprocesses
        os.environ[envKey] = name

        if name.startswith('sibling'):
            return SiblingSuiteModel(_primary_suite_path, name)
        elif name.startswith('nested'):
            return NestedImportsSuiteModel(_primary_suite_path, name)
        else:
            abort('unknown suitemodel type: ' + name)

    @staticmethod
    def siblings_dir(suite_dir):
        if exists(suite_dir):
            _, primary_vc_root = VC.get_vc_root(suite_dir, abortOnError=False)
            if not primary_vc_root:
                suite_parent = dirname(suite_dir)
                # Use the heuristic of a 'ci.hocon' file being
                # at the root of a repo that contains multiple suites.
                hocon = join(suite_parent, 'ci.hocon')
                if exists(hocon):
                    return dirname(suite_parent)
                return suite_parent
        else:
            primary_vc_root = suite_dir
        return dirname(primary_vc_root)

    @staticmethod
    def _checked_to_importee_tuple(checked, suite_import):
        """ Converts the result of `_check_exists` to a tuple containing the result of `_check_exists` and
        the directory in which the importee can be found.
        If the result of checked is the urlinfos list, this path is relative to where the repository would be checked out.
        """
        if isinstance(checked, list):
            return checked, suite_import.name if suite_import.in_subdir else None
        else:
            return checked, join(checked, suite_import.name) if suite_import.in_subdir else checked


class SiblingSuiteModel(SuiteModel):
    """All suites are siblings in the same parent directory, recorded as _suiteRootDir"""
    def __init__(self, suiteRootDir, option):
        SuiteModel.__init__(self)
        self._suiteRootDir = suiteRootDir

    def find_suite_dir(self, suite_import):
        logvv("find_suite_dir(SiblingSuiteModel({}), {})".format(self._suiteRootDir, suite_import))
        return self._search_dir(self._suiteRootDir, suite_import)

    def set_primary_dir(self, d):
        logvv("set_primary_dir(SiblingSuiteModel({}), {})".format(self._suiteRootDir, d))
        SuiteModel.set_primary_dir(self, d)
        self._suiteRootDir = SuiteModel.siblings_dir(d)
        logvv("self._suiteRootDir = {}".format(self._suiteRootDir))

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        suitename = suite_import.name
        if suitename in self.suitenamemap:
            suitename = self.suitenamemap[suitename]

        # Try use the URL first so that a big repo is cloned to a local
        # directory whose named is based on the repo instead of a suite
        # nested in the big repo.
        base = None
        for urlinfo in suite_import.urlinfos:
            if urlinfo.abs_kind() == 'source':
                # 'https://github.com/graalvm/graal.git' -> 'graal'
                base, _ = os.path.splitext(basename(_urllib_parse.urlparse(urlinfo.url).path))
                if base: break
        if base:
            path = join(SiblingSuiteModel.siblings_dir(importer_dir), base)
        else:
            path = join(SiblingSuiteModel.siblings_dir(importer_dir), suitename)
        checked = self._check_exists(suite_import, path, check_alternate)
        return SuiteModel._checked_to_importee_tuple(checked, suite_import)

    def verify_imports(self, suites, args):
        if not args:
            args = []
        results = []
        # Ensure that all suites in the same repo import the same version of other suites
        dirs = {s.vc_dir for s in suites if s.dir != s.vc_dir}
        for vc_dir in dirs:
            imports = {}
            for suite_dir in [_is_suite_dir(join(vc_dir, x)) for x in os.listdir(vc_dir) if _is_suite_dir(join(vc_dir, x))]:
                suite = SourceSuite(suite_dir, load=False, primary=True)
                for suite_import in suite.suite_imports:
                    current_import = imports.get(suite_import.name)
                    if not current_import:
                        imports[suite_import.name] = (suite, suite_import.version)
                    else:
                        importing_suite, version = current_import
                        if suite_import.version != version:
                            results.append((suite_import.name, importing_suite.dir, suite.dir))

        # Parallel suite imports may mean that multiple suites import the
        # same subsuite and if scheckimports isn't run in the right suite
        # then it creates a mismatch.
        if len(results) != 0:
            mismatches = []
            for name, suite1, suite2 in results:
                log_error('\'%s\' and \'%s\' import different versions of the suite \'%s\'' % (suite1, suite2, name))
                for s in suites:
                    if s.dir == suite1:
                        mismatches.append(suite2)
                    elif s.dir == suite2:
                        mismatches.append(suite1)
            log_error('Please adjust the other imports using this command')
            for mismatch in mismatches:
                log_error('mx -p %s scheckimports %s' % (mismatch, ' '.join(args)))
            abort('Aborting for import mismatch')

        return results


class NestedImportsSuiteModel(SuiteModel):
    """Imported suites are all siblings in an 'mx.imports/source' directory of the primary suite"""
    @staticmethod
    def _imported_suites_dirname():
        return join('mx.imports', 'source')

    def __init__(self, primaryDir, option):
        SuiteModel.__init__(self)
        self._primaryDir = primaryDir

    def find_suite_dir(self, suite_import):
        return self._search_dir(join(self._primaryDir, NestedImportsSuiteModel._imported_suites_dirname()), suite_import)

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        suitename = suite_import.name
        if suitename in self.suitenamemap:
            suitename = self.suitenamemap[suitename]
        if basename(importer_dir) == basename(self._primaryDir):
            # primary is importer
            this_imported_suites_dirname = join(importer_dir, NestedImportsSuiteModel._imported_suites_dirname())
            ensure_dir_exists(this_imported_suites_dirname)
            path = join(this_imported_suites_dirname, suitename)
        else:
            path = join(SuiteModel.siblings_dir(importer_dir), suitename)
        checked = self._check_exists(suite_import, path, check_alternate)
        return SuiteModel._checked_to_importee_tuple(checked, suite_import)

    def nestedsuites_dirname(self):
        return NestedImportsSuiteModel._imported_suites_dirname()


class SuiteImportURLInfo:
    """
    Captures the info in the {"url", "kind"} dict,
    and adds a 'vc' field.
    """
    def __init__(self, url, kind, vc):
        self.url = url
        self.kind = kind
        self.vc = vc

    def abs_kind(self):
        """ Maps vc kinds to 'source'
        """
        return self.kind if self.kind == 'binary' else 'source'


class SuiteImport:
    def __init__(self, name, version, urlinfos, kind=None, dynamicImport=False, in_subdir=False, version_from=None, suite_dir=None):
        self.name = name
        self.urlinfos = [] if urlinfos is None else urlinfos
        self.version = self._deprecated_resolve_git_branchref(version)
        self.version_from = version_from
        self.dynamicImport = dynamicImport
        self.kind = kind
        self.in_subdir = in_subdir
        self.suite_dir = suite_dir

    def __str__(self):
        return self.name

    def _deprecated_resolve_git_branchref(self, version):
        prefix = 'git-bref:'
        if not version or not version.startswith(prefix):
            return version
        if primary_suite() and not primary_suite().getMxCompatibility().supportSuiteImportGitBref():
            abort("Invalid version: {}. Automatic translation of `git-bref:` is not supported anymore".format(version))

        bref_name = version[len(prefix):]
        git_urlinfos = [urlinfo for urlinfo in self.urlinfos if urlinfo.vc.kind == 'git']
        if len(git_urlinfos) != 1:
            abort('Using ' + version + ' requires exactly one git urlinfo')
        git_url = git_urlinfos[0].url
        return SuiteImport.resolve_git_branchref(git_url, bref_name)

    @staticmethod
    def resolve_git_branchref(repo_url, bref_name, abortOnError=True):
        resolved_version = GitConfig.get_branch_remote(repo_url, bref_name)
        if not resolved_version:
            if abortOnError:
                abort('Resolving ' + bref_name + ' against ' + repo_url + ' failed')
            return None
        logv('Resolved ' + bref_name + ' against ' + repo_url + ' to ' + resolved_version)
        return resolved_version

    @staticmethod
    def parse_specification(import_dict, context, importer, dynamicImport=False):
        name = import_dict.get('name')
        if not name:
            abort('suite import must have a "name" attribute', context=context)

        urls = import_dict.get("urls")
        in_subdir = import_dict.get("subdir", False)
        version = import_dict.get("version")
        suite_dir = None
        version_from = import_dict.get("versionFrom")
        if version_from and version:
            abort("In import for '{}': 'version' and 'versionFrom' can not be both set".format(name), context=context)
        if version is None and version_from is None:
            if not (in_subdir and (importer.vc_dir != importer.dir or isinstance(importer, BinarySuite))):
                abort("In import for '{}': No version given and not a 'subdir' suite of the same repository".format(name), context=context)
            if importer.isSourceSuite():
                suite_dir = join(importer.vc_dir, name)
            version = importer.version()
        if urls is None:
            if not in_subdir:
                if import_dict.get("subdir") is None and importer.vc_dir != importer.dir:
                    warn("In import for '{}': No urls given but 'subdir' is not set, assuming 'subdir=True'".format(name), context)
                    in_subdir = True
                else:
                    abort("In import for '{}': No urls given and not a 'subdir' suite".format(name), context=context)
            return SuiteImport(name, version, None, None, dynamicImport=dynamicImport, in_subdir=in_subdir, version_from=version_from, suite_dir=suite_dir)
        # urls a list of alternatives defined as dicts
        if not isinstance(urls, list):
            abort('suite import urls must be a list', context=context)
        urlinfos = []
        mainKind = None
        for urlinfo in urls:
            if isinstance(urlinfo, dict) and urlinfo.get('url') and urlinfo.get('kind'):
                kind = urlinfo.get('kind')
                if not VC.is_valid_kind(kind):
                    abort('suite import kind ' + kind + ' illegal', context=context)
            else:
                abort('suite import url must be a dict with {"url", kind", attributes', context=context)
            vc = vc_system(kind)
            if kind != 'binary':
                assert not mainKind or mainKind == kind, "Only expecting one non-binary kind"
                mainKind = kind
            url = mx_urlrewrites.rewriteurl(urlinfo.get('url'))
            urlinfos.append(SuiteImportURLInfo(url, kind, vc))
        vc_kind = None
        if mainKind:
            vc_kind = mainKind
        elif urlinfos:
            vc_kind = 'binary'
        return SuiteImport(name, version, urlinfos, vc_kind, dynamicImport=dynamicImport, in_subdir=in_subdir, version_from=version_from, suite_dir=suite_dir)

    @staticmethod
    def get_source_urls(source, kind=None):
        """
        Returns a list of SourceImportURLInfo instances
        If source is a string (dir) determine kind, else search the list of
        urlinfos and return the values for source repos
        """
        if isinstance(source, str):
            if kind:
                vc = vc_system(kind)
            else:
                assert not source.startswith("http:")
                vc = VC.get_vc(source)
            return [SuiteImportURLInfo(mx_urlrewrites.rewriteurl(source), 'source', vc)]
        elif isinstance(source, list):
            result = [s for s in source if s.kind != 'binary']
            return result
        else:
            abort('unexpected type in SuiteImport.get_source_urls')


_primary_suite_path = None
_primary_suite = None
# List of functions to run when the primary suite is initialized
_primary_suite_deferrables = []


def _primary_suite_init(s):
    global _primary_suite
    assert not _primary_suite
    _primary_suite = s
    _primary_suite.primary = True
    os.environ['MX_PRIMARY_SUITE_PATH'] = s.dir
    for deferrable in _primary_suite_deferrables:
        deferrable()


def primary_suite():
    """:rtype: Suite"""
    return _primary_suite


class SuiteConstituent(Comparable):
    __metaclass__ = ABCMeta

    def __init__(self, suite, name):
        """
        :type name: str
        :type suite: Suite
        """
        self.name = name
        self.suite = suite

        # Should this constituent be visible outside its suite
        self.internal = False

    def origin(self):
        """
        Gets a 2-tuple (file, line) describing the source file where this constituent
        is defined or None if the location cannot be determined.
        """
        suitepy = self.suite.suite_py()
        if exists(suitepy):
            import tokenize
            with open(suitepy) as fp:
                candidate = None
                for t in tokenize.generate_tokens(fp.readline):
                    _, tval, (srow, _), _, _ = t
                    if candidate is None:
                        if tval in ('"' + self.name + '"', "'" + self.name + "'"):
                            candidate = srow
                    else:
                        if tval == ':':
                            return (suitepy, srow)
                        else:
                            candidate = None

    def __abort_context__(self):
        """
        Gets a description of where this constituent was defined in terms of source file
        and line number. If no such description can be generated, None is returned.
        """
        loc = self.origin()
        if loc:
            path, lineNo = loc
            return '  File "{}", line {} in definition of {}'.format(path, lineNo, self.name)
        return '  {}'.format(self.name)

    def _comparison_key(self):
        return self.name, self.suite

    def __cmp__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return compare(self._comparison_key(), other._comparison_key())

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._comparison_key() == other._comparison_key()

    def __ne__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._comparison_key() != other._comparison_key()

    def __hash__(self):
        return hash(self._comparison_key())

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class License(SuiteConstituent):
    def __init__(self, suite, name, fullname, url):
        SuiteConstituent.__init__(self, suite, name)
        self.fullname = fullname
        self.url = url

    def _comparison_key(self):
        # Licenses are equal across suites
        return self.name, self.url, self.fullname


class Dependency(SuiteConstituent):
    """
    A dependency is a library, distribution or project specified in a suite.
    The name must be unique across all Dependency instances.
    """
    __metaclass__ = ABCMeta

    def __init__(self, suite, name, theLicense, **kwArgs):
        SuiteConstituent.__init__(self, suite, name)
        if isinstance(theLicense, str):
            theLicense = [theLicense]
        self.theLicense = theLicense
        self.__dict__.update(kwArgs)

    def isBaseLibrary(self):
        return isinstance(self, BaseLibrary)

    def isLibrary(self):
        return isinstance(self, Library)

    def isResourceLibrary(self):
        return isinstance(self, ResourceLibrary)

    def isPackedResourceLibrary(self):
        return isinstance(self, PackedResourceLibrary)

    def isJreLibrary(self):
        return isinstance(self, JreLibrary)

    def isJdkLibrary(self):
        return isinstance(self, JdkLibrary)

    def isProject(self):
        return isinstance(self, Project)

    def isJavaProject(self):
        return isinstance(self, JavaProject)

    def isNativeProject(self):
        return isinstance(self, AbstractNativeProject)

    def isArchivableProject(self):
        return isinstance(self, ArchivableProject)

    def isMavenProject(self):
        return isinstance(self, MavenProject)

    def isDistribution(self):
        return isinstance(self, Distribution)

    def isJARDistribution(self):
        return isinstance(self, JARDistribution)

    def isLayoutJARDistribution(self):
        return isinstance(self, LayoutJARDistribution)

    def isClasspathDependency(self):
        return isinstance(self, ClasspathDependency)

    def isTARDistribution(self):
        return isinstance(self, AbstractTARDistribution)

    def isProjectOrLibrary(self):
        return self.isProject() or self.isLibrary()

    def isPlatformDependent(self):
        return False

    def getGlobalRegistry(self):
        if self.isProject():
            return _projects
        if self.isLibrary():
            return _libs
        if self.isDistribution():
            return _dists
        if self.isJreLibrary():
            return _jreLibs
        assert self.isJdkLibrary()
        return _jdkLibs

    def getSuiteRegistry(self):
        if self.isProject():
            return self.suite.projects
        if self.isLibrary():
            return self.suite.libs
        if self.isDistribution():
            return self.suite.dists
        if self.isJreLibrary():
            return self.suite.jreLibs
        assert self.isJdkLibrary()
        return self.suite.jdkLibs

    def get_output_base(self):
        return self.suite.get_output_root(platformDependent=self.isPlatformDependent())

    def getBuildTask(self, args):
        """
        Return a BuildTask that can be used to build this dependency.
        :rtype : BuildTask
        """
        nyi('getBuildTask', self)

    def abort(self, msg):
        """
        Aborts with given message prefixed by the origin of this dependency.
        """
        abort(msg, context=self)

    def warn(self, msg):
        """
        Warns with given message prefixed by the origin of this dependency.
        """
        warn(msg, context=self)

    def qualifiedName(self):
        return '{}:{}'.format(self.suite.name, self.name)

    def walk_deps(self, preVisit=None, visit=None, visited=None, ignoredEdges=None, visitEdge=None):
        """
        Walk the dependency graph rooted at this object.
        See documentation for mx.walk_deps for more info.
        """
        if visited is not None:
            if self in visited:
                return
        else:
            visited = set()
        if not ignoredEdges:
            # Default ignored edges
            ignoredEdges = [DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED, DEP_BUILD]
        self._walk_deps_helper(visited, None, preVisit, visit, ignoredEdges, visitEdge)

    def _walk_deps_helper(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        _debug_walk_deps_helper(self, edge, ignoredEdges)
        assert self not in visited, self
        visited.add(self)
        if not preVisit or preVisit(self, edge):
            self._walk_deps_visit_edges(visited, edge, preVisit, visit, ignoredEdges, visitEdge)
            if visit:
                visit(self, edge)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        nyi('_walk_deps_visit_edges', self)

    def _walk_deps_visit_edges_helper(self, deps, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        for dep_type, dep_list in deps:
            if not _is_edge_ignored(dep_type, ignoredEdges):
                for dst in dep_list:
                    out_edge = DepEdge(self, dep_type, in_edge)
                    if visitEdge:
                        visitEdge(self, dst, out_edge)
                    if dst not in visited:
                        dst._walk_deps_helper(visited, out_edge, preVisit, visit, ignoredEdges, visitEdge)

    def getArchivableResults(self, use_relpath=True, single=False):
        """
        Generates (file_path, archive_path) tuples for all the build results of this dependency.
        :param use_relpath: When `False` flattens all the results to the root of the archive
        :param single: When `True` expects a single result.
                        Might throw `ValueError` if that does not make sense for this dependency type.
        :rtype: collections.Iterable[(str, str)]
        """
        nyi('getArchivableResults', self)

    def contains_dep(self, dep, includeAnnotationProcessors=False):
        """
        Determines if the dependency graph rooted at this object contains 'dep'.
        Returns the path from this object to 'dep' if so, otherwise returns None.
        """
        if dep == self:
            return [self]
        class FoundPath(StopIteration):
            def __init__(self, path):
                StopIteration.__init__(self)
                self.path = path
        def visit(path, d, edge):
            if dep is d:
                raise FoundPath(path)
        try:
            ignoredEdges = [DEP_EXCLUDED] if includeAnnotationProcessors else None
            self.walk_deps(visit=visit, ignoredEdges=ignoredEdges)
        except FoundPath as e:
            return e.path
        return None

    """Only JavaProjects define Java packages"""
    def defined_java_packages(self):
        return []

    def mismatched_imports(self):
        return {}

    def _extra_artifact_discriminant(self):
        """
        An extra string to help identify the current build configuration. It will be used in the generated path for the
        built artifacts and will avoid unnecessary rebuilds when frequently changing this build configuration.
        :rtype : str
        """
        return ''

    def _resolveDepsHelper(self, deps, fatalIfMissing=True):
        """
        Resolves any string entries in 'deps' to the Dependency objects named
        by the strings. The 'deps' list is updated in place.
        """
        if deps:
            assert all((isinstance(d, (str, Dependency)) for d in deps))
            if isinstance(deps[0], str):
                assert all((isinstance(d, str) for d in deps))
                resolvedDeps = []
                for name in deps:
                    s, _ = splitqualname(name)
                    if s and s in _jdkProvidedSuites:
                        logvv('[{}: ignoring dependency {} as it is provided by the JDK]'.format(self, name))
                        continue
                    dep = dependency(name, context=self, fatalIfMissing=fatalIfMissing)
                    if not dep:
                        continue
                    if dep.isProject() and self.suite is not dep.suite:
                        abort('cannot have an inter-suite reference to a project: ' + dep.name, context=self)
                    if s is None and self.suite is not dep.suite:
                        current_suite_dep = self.suite.dependency(dep.name, fatalIfMissing=False)
                        if dep != current_suite_dep:
                            raise abort('inter-suite reference must use qualified form ' + dep.suite.name + ':' + dep.name, context=self)
                        dep = current_suite_dep  # prefer our version
                    if self.suite is not dep.suite and dep.internal:
                        abort('cannot reference internal ' + dep.name + ' from ' + self.suite.name + ' suite', context=self)
                    selfJC = getattr(self, 'javaCompliance', None)
                    depJC = getattr(dep, 'javaCompliance', None)
                    if selfJC and depJC and selfJC.value < depJC.value:
                        if self.suite.getMxCompatibility().checkDependencyJavaCompliance():
                            abort('cannot depend on ' + name + ' as it has a higher Java compliance than ' + str(selfJC), context=self)
                    resolvedDeps.append(dep)
                deps[:] = resolvedDeps
            assert all((isinstance(d, Dependency) for d in deps))


class Suite(object):
    """
    Command state and methods for all suite subclasses.
    :type dists: list[Distribution]
    """
    def __init__(self, mxDir, primary, internal, importing_suite, load, vc, vc_dir, dynamicallyImported=False):
        if primary is True and vc_dir is None:
            abort("The primary suite must be in a vcs repository")
        self.imported_by = [] if primary else [importing_suite]
        self.mxDir = mxDir
        self.dir = dirname(mxDir)
        self.name = _suitename(mxDir)
        self.primary = primary
        self.internal = internal
        self.libs = []
        self.jreLibs = []
        self.jdkLibs = []
        self.suite_imports = []
        self.extensions = None
        self.requiredMxVersion = None
        self.dists = []
        self._metadata_initialized = False
        self.loading_imports = False
        self.post_init = False
        self.resolved_dependencies = False
        self.distTemplates = []
        self.licenseDefs = []
        self.repositoryDefs = []
        self.javacLintOverrides = []
        self.versionConflictResolution = 'none' if importing_suite is None else importing_suite.versionConflictResolution
        self.dynamicallyImported = dynamicallyImported
        self.scm = None
        self._outputRoot = None
        self._preloaded_suite_dict = None
        self.vc = vc
        self.vc_dir = vc_dir
        self._preload_suite_dict()
        self._init_imports()
        if load:
            self._load()

    def __str__(self):
        return self.name

    def _load(self):
        """
        Calls _parse_env and _load_extensions
        """
        logvv("Loading suite " + self.name)
        self._load_suite_dict()
        self._parse_env()
        self._load_extensions()

    def getMxCompatibility(self):
        return mx_compat.getMxCompatibility(self.requiredMxVersion)

    def dependency(self, name, fatalIfMissing=True, context=None):
        """
        Find a dependency defined by this Suite.
        """
        def _find_in_registry(reg):
            for lib in reg:
                if lib.name == name:
                    return lib
        result = _find_in_registry(self.libs) or \
                 _find_in_registry(self.jreLibs) or \
                 _find_in_registry(self.jdkLibs) or \
                 _find_in_registry(self.dists)
        if fatalIfMissing and result is None:
            abort("Couldn't find '{}' in '{}'".format(name, self.name), context=context)
        return result

    def _parse_env(self):
        nyi('_parse_env', self)

    def get_output_root(self, platformDependent=False):
        """
        Gets the root of the directory hierarchy under which generated artifacts for this
        suite such as class files and annotation generated sources should be placed.
        """
        if not self._outputRoot:
            outputRoot = self._get_early_suite_dict_property('outputRoot')
            if outputRoot:
                self._outputRoot = realpath(_make_absolute(outputRoot.replace('/', os.sep), self.dir))
            elif get_env('MX_ALT_OUTPUT_ROOT') is not None:
                self._outputRoot = realpath(_make_absolute(join(get_env('MX_ALT_OUTPUT_ROOT'), self.name), self.dir))
            else:
                self._outputRoot = self.getMxCompatibility().getSuiteOutputRoot(self)
        if platformDependent:
            return os.path.join(self._outputRoot, get_os() + '-' + get_arch())
        else:
            return self._outputRoot

    def get_mx_output_dir(self):
        """
        Gets the directory into which mx bookkeeping artifacts should be placed.
        """
        return join(self.get_output_root(), basename(self.mxDir))

    def _preload_suite_dict(self):
        dictName = 'suite'
        moduleName = 'suite'
        modulePath = self.suite_py()
        assert modulePath.endswith(moduleName + ".py")
        if not exists(modulePath):
            abort('{} is missing'.format(modulePath))

        savedModule = sys.modules.get(moduleName)
        if savedModule:
            warn(modulePath + ' conflicts with ' + savedModule.__file__)
        # temporarily extend the Python path
        sys.path.insert(0, self.mxDir)

        snapshot = frozenset(sys.modules.keys())
        module = __import__(moduleName)

        if savedModule:
            # restore the old module into the module name space
            sys.modules[moduleName] = savedModule
        else:
            # remove moduleName from the module name space
            sys.modules.pop(moduleName)

        # For now fail fast if extra modules were loaded.
        # This can later be relaxed to simply remove the extra modules
        # from the sys.modules name space if necessary.
        extraModules = frozenset(sys.modules.keys()) - snapshot
        assert len(extraModules) == 0, 'loading ' + modulePath + ' caused extra modules to be loaded: ' + ', '.join([m for m in extraModules])

        # revert the Python path
        del sys.path[0]

        def expand(value, context):
            if isinstance(value, dict):
                for n, v in value.items():
                    value[n] = expand(v, context + [n])
            elif isinstance(value, list):
                for i in range(len(value)):
                    value[i] = expand(value[i], context + [str(i)])
            elif isinstance(value, str):
                value = expandvars(value)
                if '$' in value or '%' in value:
                    abort('value of ' + '.'.join(context) + ' contains an undefined environment variable: ' + value)
            elif isinstance(value, bool):
                pass
            else:
                abort('value of ' + '.'.join(context) + ' is of unexpected type ' + str(type(value)))

            return value

        if not hasattr(module, dictName):
            abort(modulePath + ' must define a variable named "' + dictName + '"')

        self._preloaded_suite_dict = expand(getattr(module, dictName), [dictName])

        if self.name == 'mx':
            self.requiredMxVersion = version
        elif 'mxversion' in self._preloaded_suite_dict:
            try:
                self.requiredMxVersion = VersionSpec(self._preloaded_suite_dict['mxversion'])
            except AssertionError as ae:
                abort('Exception while parsing "mxversion" in suite file: ' + str(ae), context=self)

        conflictResolution = self._preloaded_suite_dict.get('versionConflictResolution')
        if conflictResolution:
            self.versionConflictResolution = conflictResolution

        _imports = self._preloaded_suite_dict.get('imports', {})
        for _suite in _imports.get('suites', []):
            context = "suite import '" + _suite.get('name', '<undefined>') + "'"
            os_arch = Suite._pop_os_arch(_suite, context)
            Suite._merge_os_arch_attrs(_suite, os_arch, context)

        (jsonifiable, errorMessage) = self._is_jsonifiable(modulePath)
        if not jsonifiable:
            msg = "Cannot parse file {}. Please make sure that this file only contains dicts and arrays. {}".format(modulePath, errorMessage)
            if self.getMxCompatibility().requireJsonifiableSuite():
                abort(msg)
            else:
                warn(msg)

    def _is_jsonifiable(self, suiteFile):
        """Other tools require the suite.py files to be parseable without running a python interpreter.
        Therefore suite.py file must consist out of JSON like dict, array, string, integer and boolean
        structures. Function calls, string concatenations and other python expressions are not allowed."""
        with open(suiteFile, "r") as f:
            suiteContents = f.read()
        try:
            result = re.match(".*?suite\\s*=\\s*(\\{.*)", suiteContents, re.DOTALL)
            part = result.group(1)
            stack = 0
            endIdx = 0
            for c in part:
                if c == "{":
                    stack += 1
                elif c == "}":
                    stack -= 1
                endIdx += 1
                if stack == 0:
                    break
            part = part[:endIdx]

            # convert python boolean constants to json boolean constants
            part = re.sub("True", "true", part)
            part = re.sub("False", "false", part)

            # remove python comments
            part = re.sub("(.*?)#.*", "\\1", part)
            def python_to_json_string(m):
                return "\"" + m.group(1).replace("\n", "\\n") + "\""

            # remove all spaces between a comma and ']' or '{'
            part = re.sub(",\\s*(\\]|\\})", "\\1", part)

            # convert python multiline strings to json strings with embedded newlines
            part = re.sub("\"\"\"(.*?)\"\"\"", python_to_json_string, part, flags=re.DOTALL)
            part = re.sub("'''(.*?)'''", python_to_json_string, part, flags=re.DOTALL)

            # convert python single-quoted strings to json double-quoted strings
            part = re.sub("'(.*?)'", python_to_json_string, part, flags=re.DOTALL)

            json.loads(part)
            return (True, None)
        except:
            return (False, sys.exc_info()[1])

    def _register_url_rewrites(self):
        urlrewrites = self._get_early_suite_dict_property('urlrewrites')
        if urlrewrites:
            for urlrewrite in urlrewrites:
                def _error(msg):
                    abort(msg, context=self)
                mx_urlrewrites.register_urlrewrite(urlrewrite, onError=_error)

    def _load_suite_dict(self):
        supported = [
            'imports',
            'projects',
            'libraries',
            'jrelibraries',
            'jdklibraries',
            'distributions',
            'name',
            'outputRoot',
            'mxversion',
            'sourceinprojectwhitelist',
            'versionConflictResolution',
            'developer',
            'url',
            'licenses',
            'licences',
            'defaultLicense',
            'defaultLicence',
            'snippetsPattern',
            'repositories',
            'javac.lint.overrides',
            'urlrewrites',
            'scm',
            'version',
            'externalProjects',
            'groupId',
            'release',
        ]
        if self._preloaded_suite_dict is None:
            self._preload_suite_dict()
        d = self._preloaded_suite_dict

        if self.requiredMxVersion is None:
            self.requiredMxVersion = mx_compat.minVersion()
            warn("The {} suite does not express any required mx version. Assuming version {}. Consider adding 'mxversion=<version>' to your suite file ({}).".format(self.name, self.requiredMxVersion, self.suite_py()))
        elif self.requiredMxVersion > version:
            mx = join(_mx_home, 'mx')
            if _mx_home in os.environ['PATH'].split(os.pathsep):
                mx = 'mx'
            abort("The {} suite requires mx version {} while your current mx version is {}.\nPlease update mx by running \"{} update\"".format(self.name, self.requiredMxVersion, version, mx))
        if not self.getMxCompatibility():
            abort("The {} suite requires mx version {} while your version of mx only supports suite versions {} to {}.".format(self.name, self.requiredMxVersion, mx_compat.minVersion(), version))

        javacLintOverrides = d.get('javac.lint.overrides', None)
        if javacLintOverrides:
            self.javacLintOverrides = javacLintOverrides.split(',')

        if d.get('snippetsPattern'):
            self.snippetsPattern = d.get('snippetsPattern')

        unknown = set(d.keys()) - frozenset(supported)

        suiteExtensionAttributePrefix = self.name + ':'
        suiteSpecific = {n[len(suiteExtensionAttributePrefix):]: d[n] for n in d.keys() if n.startswith(suiteExtensionAttributePrefix) and n != suiteExtensionAttributePrefix}
        for n, v in suiteSpecific.items():
            if hasattr(self, n):
                abort('Cannot override built-in suite attribute "' + n + '"', context=self)
            setattr(self, n, v)
            unknown.remove(suiteExtensionAttributePrefix + n)

        if unknown:
            abort(self.suite_py() + ' defines unsupported suite attribute: ' + ', '.join(unknown))

        self.suiteDict = d
        self._preloaded_suite_dict = None

    def _register_metadata(self):
        """
        Registers the metadata loaded by _load_metadata into the relevant
        global dictionaries such as _projects, _libs, _jreLibs and _dists.
        """
        for l in self.libs:
            existing = _libs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l and _check_global_structures:
                abort('inconsistent library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _libs[l.name] = l
        for l in self.jreLibs:
            existing = _jreLibs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l:
                abort('inconsistent JRE library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _jreLibs[l.name] = l
        for l in self.jdkLibs:
            existing = _jdkLibs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l:
                abort('inconsistent JDK library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _jdkLibs[l.name] = l
        for d in self.dists:
            self._register_distribution(d)
        for d in self.distTemplates:
            existing = _distTemplates.get(d.name)
            if existing is not None and _check_global_structures:
                abort('inconsistent distribution template redefinition of ' + d.name + ' in ' + existing.suite.dir + ' and ' + d.suite.dir, context=d)
            _distTemplates[d.name] = d
        for l in self.licenseDefs:
            existing = _licenses.get(l.name)
            if existing is not None and _check_global_structures and l != existing:
                abort("inconsistent license redefinition of {} in {} (initialy defined in {})".format(l.name, self.name, existing.suite.name), context=l)
            _licenses[l.name] = l
        for r in self.repositoryDefs:
            existing = _repositories.get(r.name)
            if existing is not None and _check_global_structures and r != existing:
                abort("inconsistent repository redefinition of {} in {} (initialy defined in {})".format(r.name, self.name, existing.suite.name), context=r)
            _repositories[r.name] = r

    def _register_distribution(self, d):
        existing = _dists.get(d.name)
        if existing is not None and _check_global_structures:
            warn('distribution ' + d.name + ' redefined', context=d)
        _dists[d.name] = d

    def _resolve_dependencies(self):
        for d in self.libs + self.jdkLibs + self.dists:
            d.resolveDeps()
        for r in self.repositoryDefs:
            r.resolveLicenses()
        self.resolved_dependencies = True

    def _post_init_finish(self):
        if hasattr(self, 'mx_post_parse_cmd_line'):
            self.mx_post_parse_cmd_line(_opts)
        self.post_init = True

    def version(self, abortOnError=True):
        abort('version not implemented')

    def isDirty(self, abortOnError=True):
        abort('isDirty not implemented')

    def _load_metadata(self):
        suiteDict = self.suiteDict
        if suiteDict.get('name') is None:
            abort('Missing "suite=<name>" in ' + self.suite_py())

        libsMap = self._check_suiteDict('libraries')
        jreLibsMap = self._check_suiteDict('jrelibraries')
        jdkLibsMap = self._check_suiteDict('jdklibraries')
        distsMap = self._check_suiteDict('distributions')
        importsMap = self._check_suiteDict('imports')
        scmDict = self._check_suiteDict('scm')
        self.developer = self._check_suiteDict('developer')
        self.url = suiteDict.get('url')
        if not _validate_abolute_url(self.url, acceptNone=True):
            abort('Invalid url in {}'.format(self.suite_py()))
        self.defaultLicense = suiteDict.get(self.getMxCompatibility().defaultLicenseAttribute())
        if isinstance(self.defaultLicense, str):
            self.defaultLicense = [self.defaultLicense]

        if scmDict:
            try:
                read = scmDict.pop('read')
            except NameError:
                abort("Missing required 'read' attribute for 'scm'", context=self)
            write = scmDict.pop('write', read)
            url = scmDict.pop('url', read)
            self.scm = SCMMetadata(url, read, write)

        for name, attrs in sorted(jreLibsMap.items()):
            jar = attrs.pop('jar')
            # JRE libraries are optional by default
            optional = attrs.pop('optional', 'true') != 'false'
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            l = JreLibrary(self, name, jar, optional, theLicense, **attrs)
            self.jreLibs.append(l)

        for name, attrs in sorted(jdkLibsMap.items()):
            path = attrs.pop('path')
            deps = Suite._pop_list(attrs, 'dependencies', context='jdklibrary ' + name)
            # JRE libraries are optional by default
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            optional = attrs.pop('optional', False)
            if isinstance(optional, str):
                optional = optional != 'false'
            jdkStandardizedSince = JavaCompliance(attrs.pop('jdkStandardizedSince', '1.2'))
            l = JdkLibrary(self, name, path, deps, optional, theLicense, jdkStandardizedSince=jdkStandardizedSince, **attrs)
            self.jdkLibs.append(l)

        for name, attrs in sorted(importsMap.items()):
            if name == 'suites':
                pass
            elif name == 'libraries':
                self._load_libraries(attrs)
            else:
                abort('illegal import kind: ' + name)

        licenseDefs = self._check_suiteDict(self.getMxCompatibility().licensesAttribute())
        repositoryDefs = self._check_suiteDict('repositories')

        if suiteDict.get('release') not in [None, True, False]:
            abort("Invalid 'release' attribute: it should be a boolean", context=self)

        self._load_libraries(libsMap)
        self._load_distributions(distsMap)
        self._load_licenses(licenseDefs)
        self._load_repositories(repositoryDefs)

    def _check_suiteDict(self, key):
        return dict() if self.suiteDict.get(key) is None else self.suiteDict[key]

    def imports_dir(self, kind):
        return join(join(self.dir, 'mx.imports'), kind)

    def binary_imports_dir(self):
        return self.imports_dir('binary')

    def source_imports_dir(self):
        return self.imports_dir('source')

    def binary_suite_dir(self, name):
        """
        Returns the mxDir for an imported BinarySuite, creating the parent if necessary
        """
        dotMxDir = self.binary_imports_dir()
        ensure_dir_exists(dotMxDir)
        return join(dotMxDir, name)

    def _find_binary_suite_dir(self, name):
        """Attempts to locate a binary_suite directory for suite 'name', returns the mx dir or None"""
        suite_dir = join(self.binary_imports_dir(), name)
        return _is_suite_dir(suite_dir, _mxDirName(name))

    def _extensions_name(self):
        return 'mx_' + self.name.replace('-', '_')

    def _find_extensions(self, name):
        extensionsPath = join(self.mxDir, name + '.py')
        if exists(extensionsPath):
            return name
        else:
            return None

    def _load_extensions(self):
        extensionsName = self._find_extensions(self._extensions_name())
        if extensionsName is not None:
            if extensionsName in sys.modules:
                abort(extensionsName + '.py in suite ' + self.name + ' duplicates ' + sys.modules[extensionsName].__file__)
            # temporarily extend the Python path
            sys.path.insert(0, self.mxDir)
            with currently_loading_suite.set_scoped(self):
                mod = __import__(extensionsName)

                self.extensions = sys.modules[extensionsName]

                # revert the Python path
                del sys.path[0]

                if hasattr(mod, 'mx_post_parse_cmd_line'):
                    self.mx_post_parse_cmd_line = mod.mx_post_parse_cmd_line

                if hasattr(mod, 'mx_register_dynamic_suite_constituents'):
                    self.mx_register_dynamic_suite_constituents = mod.mx_register_dynamic_suite_constituents  # pylint: disable=C0103
                    """
                    Extension point for suites that want to dynamically create projects or distributions.
                    Such suites should define `mx_register_dynamic_suite_constituents(register_project, register_distribution)` at the
                    module level. `register_project` and `register_distribution` take 1 argument (the project/distribution object).
                    """

                if hasattr(mod, 'mx_init'):
                    mod.mx_init(self)
                self.extensions = mod

    def _get_early_suite_dict_property(self, name, default=None):
        if self._preloaded_suite_dict is not None:
            return self._preloaded_suite_dict.get(name, default)
        else:
            return self.suiteDict.get(name, default)

    def _init_imports(self):
        importsMap = self._get_early_suite_dict_property('imports', {})
        suiteImports = importsMap.get("suites")
        if suiteImports:
            if not isinstance(suiteImports, list):
                abort('suites must be a list-valued attribute')
            for entry in suiteImports:
                if not isinstance(entry, dict):
                    abort('suite import entry must be a dict')

                import_dict = entry
                imported_suite_name = import_dict.get('name', '<unknown>')
                if import_dict.get('ignore', False):
                    log("Ignoring '{}' on your platform ({}/{})".format(imported_suite_name, get_os(), get_arch()))
                    continue
                if import_dict.get('dynamic', False) and imported_suite_name not in (name for name, _ in get_dynamic_imports()):
                    continue
                suite_import = SuiteImport.parse_specification(import_dict, context=self, importer=self, dynamicImport=self.dynamicallyImported)
                jdkProvidedSince = import_dict.get('jdkProvidedSince', None)
                if jdkProvidedSince and get_jdk(tag=DEFAULT_JDK_TAG).javaCompliance >= jdkProvidedSince:
                    _jdkProvidedSuites.add(suite_import.name)
                else:
                    self.suite_imports.append(suite_import)

    def re_init_imports(self):
        """
        If a suite is updated, e.g. by sforceimports, we must re-initialize the potentially
        stale import data from the updated suite.py file
        """
        self.suite_imports = []
        self._preload_suite_dict()
        self._init_imports()

    def _load_distributions(self, distsMap):
        for name, attrs in sorted(distsMap.items()):
            if '<' in name:
                parameters = re.findall(r'<(.+?)>', name)
                self.distTemplates.append(DistributionTemplate(self, name, attrs, parameters))
            else:
                self._load_distribution(name, attrs)

    def _load_distribution(self, name, attrs):
        """:rtype : Distribution"""
        assert not '>' in name
        context = 'distribution ' + name
        className = attrs.pop('class', None)
        native = attrs.pop('native', False)
        theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
        os_arch = Suite._pop_os_arch(attrs, context)
        Suite._merge_os_arch_attrs(attrs, os_arch, context)
        exclLibs = Suite._pop_list(attrs, 'exclude', context)
        deps = Suite._pop_list(attrs, 'dependencies', context)
        pd = attrs.pop('platformDependent', False)
        platformDependent = bool(os_arch) or pd
        testDistribution = attrs.pop('testDistribution', None)
        path = attrs.pop('path', None)
        layout = attrs.pop('layout', None)
        if className:
            if not self.extensions or not hasattr(self.extensions, className):
                abort('Distribution {} requires a custom class ({}) which was not found in {}'.format(name, className, join(self.mxDir, self._extensions_name() + '.py')))
            d = getattr(self.extensions, className)(self, name, deps, exclLibs, platformDependent, theLicense, testDistribution=testDistribution, **attrs)
        elif native:
            if layout is not None:
                d = LayoutTARDistribution(self, name, deps, layout, path, platformDependent, theLicense, testDistribution=testDistribution, **attrs)
            else:
                relpath = attrs.pop('relpath', False)
                output = attrs.pop('output', None)
                d = NativeTARDistribution(self, name, deps, path, exclLibs, platformDependent, theLicense, relpath, output, testDistribution=testDistribution, **attrs)
        elif layout is not None:
            d = LayoutJARDistribution(self, name, deps, layout, path, platformDependent, theLicense, testDistribution=testDistribution, **attrs)
        else:
            subDir = attrs.pop('subDir', None)
            sourcesPath = attrs.pop('sourcesPath', None)
            if sourcesPath == "<unified>":
                sourcesPath = path
            mainClass = attrs.pop('mainClass', None)
            distDeps = Suite._pop_list(attrs, 'distDependencies', context)
            manifestEntries = attrs.pop('manifestEntries', None)
            javaCompliance = attrs.pop('javaCompliance', None)
            maven = attrs.pop('maven', True)
            stripConfigFileNames = attrs.pop('strip', None)
            stripMappingFileNames = attrs.pop('stripMap', None)
            assert stripConfigFileNames is None or isinstance(stripConfigFileNames, list)
            if isinstance(maven, dict) and maven.get('version', None):
                abort("'version' is not supported in maven specification for distributions")
            if attrs.pop('buildDependencies', None):
                abort("'buildDependencies' is not supported for JAR distributions")
            d = JARDistribution(self, name, subDir, path, sourcesPath, deps, mainClass, exclLibs, distDeps,
                                javaCompliance, platformDependent, theLicense, maven=maven,
                                stripConfigFileNames=stripConfigFileNames, stripMappingFileNames=stripMappingFileNames,
                                testDistribution=testDistribution, manifestEntries=manifestEntries, **attrs)
        self.dists.append(d)
        return d

    def _unload_unregister_distribution(self, name):
        self.dists = [d for d in self.dists if d.name != name]
        d = _dists[name]
        del _dists[name]
        return d

    @staticmethod
    def _pop_list(attrs, name, context):
        v = attrs.pop(name, None)
        if not v:
            return []
        if not isinstance(v, list):
            abort('Attribute "' + name + '" for ' + context + ' must be a list', context)
        return v

    @staticmethod
    def _pop_os_arch(attrs, context):
        os_arch = attrs.pop('os_arch', None)
        if os_arch:
            os_attrs = os_arch.pop(get_os(), None)
            if not os_attrs:
                os_attrs = os_arch.pop('<others>', None)
            if os_attrs:
                arch_attrs = os_attrs.pop(get_arch(), None)
                if not arch_attrs:
                    arch_attrs = os_attrs.pop('<others>', None)
                if arch_attrs:
                    return arch_attrs
                else:
                    warn("No platform-specific definition is available for {} for your architecture ({})".format(context, get_arch()))
            else:
                warn("No platform-specific definition is available for {} for your OS ({})".format(context, get_os()))
        return None

    @staticmethod
    def _merge_os_arch_attrs(attrs, os_arch_attrs, context, path=''):
        if os_arch_attrs:
            for k, v in os_arch_attrs.items():
                if k in attrs:
                    other = attrs[k]
                    key_path = path + '.' + str(k)
                    if isinstance(v, dict) and isinstance(other, dict):
                        Suite._merge_os_arch_attrs(other, v, context, key_path)
                    elif isinstance(v, list) and isinstance(other, list):
                        attrs[k] = v + other
                    else:
                        abort("OS/Arch attribute must not override non-OS/Arch attribute '{}' in {}".format(key_path, context))
                else:
                    attrs[k] = v

    def _load_libraries(self, libsMap):
        for name, attrs in sorted(libsMap.items()):
            context = 'library ' + name
            attrs.pop('native', False)  # TODO use to make non-classpath libraries
            os_arch = Suite._pop_os_arch(attrs, context)
            Suite._merge_os_arch_attrs(attrs, os_arch, context)
            deps = Suite._pop_list(attrs, 'dependencies', context)
            path = attrs.pop('path', None)
            urls = Suite._pop_list(attrs, 'urls', context)
            sha1 = attrs.pop('sha1', None)
            ext = attrs.pop('ext', None)
            maven = attrs.get('maven', None)

            def _check_maven(maven):
                maven_attrs = ['groupId', 'artifactId', 'version']
                if not isinstance(maven, dict) or any(x not in maven for x in maven_attrs):
                    abort('The "maven" attribute must be a dictionary containing "{0}"'.format('", "'.join(maven_attrs)), context)
                if self.getMxCompatibility().mavenSupportsClassifier():
                    if 'suffix' in maven:
                        abort('The use of "suffix" as maven metadata is not supported in this version of mx. Use "classifier" instead.', context)
                elif 'suffix' in maven:
                    maven['classifier'] = maven['suffix']
                    del maven['suffix']

            def _maven_download_urls(groupId, artifactId, version, classifier=None, baseURL=None):
                if baseURL is None:
                    baseURLs = _mavenRepoBaseURLs
                else:
                    baseURLs = [baseURL]
                args = {
                    'groupId': groupId.replace('.', '/'),
                    'artifactId': artifactId,
                    'version': version,
                    'classifier' : '-{0}'.format(classifier) if classifier else ''
                }
                return ["{base}{groupId}/{artifactId}/{version}/{artifactId}-{version}{classifier}.jar".format(base=base, **args) for base in baseURLs]

            optional = attrs.pop('optional', False)
            if not urls and maven is not None:
                _check_maven(maven)
                urls = _maven_download_urls(**maven)

            if path is None and not optional:
                if not urls:
                    abort('Library without "path" attribute must have a non-empty "urls" list attribute or "maven" attribute', context)
                if not sha1:
                    abort('Library without "path" attribute must have a non-empty "sha1" attribute', context)
                path = _get_path_in_cache(name, sha1, urls, ext, sources=False)
            sourcePath = attrs.pop('sourcePath', None)
            sourceUrls = Suite._pop_list(attrs, 'sourceUrls', context)
            sourceSha1 = attrs.pop('sourceSha1', None)
            sourceExt = attrs.pop('sourceExt', None)
            if sourcePath is None:
                if sourceSha1 and not sourceUrls:
                    # There is a sourceSha1 but no sourceUrls. Lets try to get one from maven.
                    if maven is not None:
                        _check_maven(maven)
                        if 'classifier' in maven:
                            abort('Cannot download sources for "maven" library with "classifier" attribute', context)
                        sourceUrls = _maven_download_urls(classifier='sources', **maven)
                if sourceUrls:
                    if not sourceSha1:
                        abort('Library without "sourcePath" attribute but with non-empty "sourceUrls" attribute must have a non-empty "sourceSha1" attribute', context)
                    sourcePath = _get_path_in_cache(name, sourceSha1, sourceUrls, sourceExt, sources=True)
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            resource = attrs.pop('resource', False)
            packedResource = attrs.pop('packedResource', False)
            if packedResource:
                l = PackedResourceLibrary(self, name, path, optional, urls, sha1, **attrs)
            elif resource:
                l = ResourceLibrary(self, name, path, optional, urls, sha1, **attrs)
            else:
                l = Library(self, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps, theLicense, **attrs)
            self.libs.append(l)

    def _load_licenses(self, licenseDefs):
        for name, attrs in sorted(licenseDefs.items()):
            fullname = attrs.pop('name')
            url = attrs.pop('url')
            if not _validate_abolute_url(url):
                abort('Invalid url in license {} in {}'.format(name, self.suite_py()))
            l = License(self, name, fullname, url)
            l.__dict__.update(attrs)
            self.licenseDefs.append(l)

    def _load_repositories(self, repositoryDefs):
        for name, attrs in sorted(repositoryDefs.items()):
            context = 'repository ' + name
            if 'url' in attrs:
                snapshots_url = attrs.pop('url')
                releases_url = snapshots_url
            else:
                snapshots_url = attrs.pop('snapshotsUrl')
                releases_url = attrs.pop('releasesUrl')
            if not _validate_abolute_url(snapshots_url):
                abort('Invalid url in repository {}: {}'.format(self.suite_py(), snapshots_url), context=context)
            if releases_url != snapshots_url and not _validate_abolute_url(releases_url):
                abort('Invalid url in repository {}: {}'.format(self.suite_py(), releases_url), context=context)
            licenses = Suite._pop_list(attrs, self.getMxCompatibility().licensesAttribute(), context=context)
            r = Repository(self, name, snapshots_url, releases_url, licenses)
            r.__dict__.update(attrs)
            self.repositoryDefs.append(r)

    def recursive_post_init(self):
        """depth first _post_init driven by imports graph"""
        self.visit_imports(Suite._init_metadata_visitor)
        self._init_metadata()
        self.visit_imports(Suite._resolve_dependencies_visitor)
        self._resolve_dependencies()
        self.visit_imports(Suite._post_init_visitor)
        self._post_init()

    @staticmethod
    def _init_metadata_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite._metadata_initialized:
            # avoid recursive initialization
            imported_suite._metadata_initialized = True
            imported_suite.visit_imports(imported_suite._init_metadata_visitor)
            imported_suite._init_metadata()

    @staticmethod
    def _post_init_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite.post_init:
            imported_suite.visit_imports(imported_suite._post_init_visitor)
            imported_suite._post_init()

    @staticmethod
    def _resolve_dependencies_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite.resolved_dependencies:
            imported_suite.visit_imports(imported_suite._resolve_dependencies_visitor)
            imported_suite._resolve_dependencies()

    def _init_metadata(self):
        self._load_metadata()
        self._register_metadata()

    def _post_init(self):
        self._post_init_finish()

    def visit_imports(self, visitor, **extra_args):
        """
        Visitor support for the suite imports list
        For each entry the visitor function is called with this suite, a SuiteImport instance created
        from the entry and any extra args passed to this call.
        N.B. There is no built-in support for avoiding visiting the same suite multiple times,
        as this function only visits the imports of a single suite. If a (recursive) visitor function
        wishes to visit a suite exactly once, it must manage that through extra_args.
        """
        for suite_import in self.suite_imports:
            visitor(self, suite_import, **extra_args)

    def get_import(self, suite_name):
        for suite_import in self.suite_imports:
            if suite_import.name == suite_name:
                return suite_import
        return None

    def import_suite(self, name, version=None, urlinfos=None, kind=None, in_subdir=False):
        """Dynamic import of a suite. Returns None if the suite cannot be found"""
        imported_suite = suite(name, fatalIfMissing=False)
        if imported_suite:
            return imported_suite
        suite_import = SuiteImport(name, version, urlinfos, kind, dynamicImport=True, in_subdir=in_subdir)
        imported_suite, cloned = _find_suite_import(self, suite_import, fatalIfMissing=False, load=False, clone_binary_first=True)
        if imported_suite:
            if not cloned and imported_suite.isBinarySuite():
                if imported_suite.vc.update(imported_suite.vc_dir, rev=suite_import.version, mayPull=True):
                    imported_suite.re_init_imports()
                    imported_suite.reload_binary_suite()
            for suite_import in imported_suite.suite_imports:
                if not suite(suite_import.name, fatalIfMissing=False):
                    warn("Programmatically imported suite '{}' imports '{}' which is not loaded.".format(name, suite_import.name))
            _register_suite(imported_suite)
            assert not imported_suite.post_init
            imported_suite._load()
            imported_suite._init_metadata()
            imported_suite._resolve_dependencies()
            imported_suite._post_init()
            if not imported_suite.isBinarySuite():
                for dist in imported_suite.dists:
                    dist.post_init()
        return imported_suite

    def scm_metadata(self, abortOnError=False):
        return self.scm

    def suite_py(self):
        return join(self.mxDir, 'suite.py')

    def suite_py_mtime(self):
        if not hasattr(self, '_suite_py_mtime'):
            self._suite_py_mtime = getmtime(self.suite_py())
        return self._suite_py_mtime

    def __abort_context__(self):
        """
        Returns a string describing where this suite was defined in terms its source file.
        If no such description can be generated, returns None.
        """
        path = self.suite_py()
        if exists(path):
            return 'In definition of suite {} in {}'.format(self.name, path)
        return None

    def isBinarySuite(self):
        return isinstance(self, BinarySuite)

    def isSourceSuite(self):
        return isinstance(self, SourceSuite)


def _resolve_suite_version_conflict(suiteName, existingSuite, existingVersion, existingImporter, otherImport, otherImportingSuite, dry_run=False):
    conflict_resolution = _opts.version_conflict_resolution
    if otherImport.dynamicImport and (not existingSuite or not existingSuite.dynamicallyImported) and conflict_resolution != 'latest_all':
        return None
    if not otherImport.version:
        return None
    if conflict_resolution == 'suite':
        if otherImportingSuite:
            conflict_resolution = otherImportingSuite.versionConflictResolution
        elif not dry_run:
            warn("Conflict resolution was set to 'suite' but importing suite is not available")

    if conflict_resolution == 'ignore':
        if not dry_run:
            warn("mismatched import versions on '{}' in '{}' ({}) and '{}' ({})".format(suiteName, otherImportingSuite.name, otherImport.version, existingImporter.name if existingImporter else '?', existingVersion))
        return None
    elif conflict_resolution in ('latest', 'latest_all'):
        if not existingSuite:
            return None # can not resolve at the moment
        if existingSuite.vc.kind != otherImport.kind:
            return None
        if not isinstance(existingSuite, SourceSuite):
            if dry_run:
                return 'ERROR'
            else:
                abort("mismatched import versions on '{}' in '{}' and '{}', 'latest' conflict resolution is only supported for source suites".format(suiteName, otherImportingSuite.name, existingImporter.name if existingImporter else '?'))
        if not existingSuite.vc.exists(existingSuite.vc_dir, rev=otherImport.version):
            return otherImport.version
        resolved = existingSuite.vc.latest(existingSuite.vc_dir, otherImport.version, existingSuite.vc.parent(existingSuite.vc_dir))
        # TODO currently this only handles simple DAGs and it will always do an update assuming that the repo is at a version controlled by mx
        if existingSuite.vc.parent(existingSuite.vc_dir) == resolved:
            return None
        return resolved
    if conflict_resolution == 'none':
        if dry_run:
            return 'ERROR'
        else:
            abort("mismatched import versions on '{}' in '{}' ({}) and '{}' ({})".format(suiteName, otherImportingSuite.name, otherImport.version, existingImporter.name if existingImporter else '?', existingVersion))
    return None

### ~~~~~~~~~~~~~ Repository / Suite
class Repository(SuiteConstituent):
    """A Repository is a remote binary repository that can be used to upload binaries with deploy_binary."""
    def __init__(self, suite, name, snapshots_url, releases_url, licenses):
        SuiteConstituent.__init__(self, suite, name)
        self.snapshots_url = snapshots_url
        self.releases_url = releases_url
        self.licenses = licenses
        self.url = snapshots_url  # for compatibility

    def get_url(self, version, rewrite=True):
        url = self.snapshots_url if version.endswith('-SNAPSHOT') else self.releases_url
        if rewrite:
            url = mx_urlrewrites.rewriteurl(url)
        return url

    def _comparison_key(self):
        return self.name, self.snapshots_url, self.releases_url, tuple((l.name if isinstance(l, License) else l for l in self.licenses))

    def resolveLicenses(self):
        self.licenses = get_license(self.licenses)

class SourceSuite(Suite):
    """A source suite"""
    def __init__(self, mxDir, primary=False, load=True, internal=False, importing_suite=None, dynamicallyImported=False):
        vc, vc_dir = VC.get_vc_root(dirname(mxDir), abortOnError=False)
        Suite.__init__(self, mxDir, primary, internal, importing_suite, load, vc, vc_dir, dynamicallyImported=dynamicallyImported)
        logvv("SourceSuite.__init__({}), got vc={}, vc_dir={}".format(mxDir, self.vc, self.vc_dir))
        self.projects = []
        self._releaseVersion = {}

    def dependency(self, name, fatalIfMissing=True, context=None):
        for p in self.projects:
            if p.name == name:
                return p
        return super(SourceSuite, self).dependency(name, fatalIfMissing=fatalIfMissing, context=context)

    def _resolve_dependencies(self):
        for d in self.projects:
            d.resolveDeps()
        super(SourceSuite, self)._resolve_dependencies()

    def version(self, abortOnError=True):
        """
        Return the current head changeset of this suite.
        """
        # we do not cache the version because it changes in development
        if not self.vc:
            return None
        return self.vc.parent(self.vc_dir, abortOnError=abortOnError)

    def isDirty(self, abortOnError=True):
        """
        Check whether there are pending changes in the source.
        """
        return self.vc.isDirty(self.vc_dir, abortOnError=abortOnError)

    def is_release(self):
        """
        Returns True if the release tag from VC is known and is not a snapshot
        """
        _release = self._get_early_suite_dict_property('release')
        if _release is not None:
            return _release
        _version = self._get_early_suite_dict_property('version')
        if _version:
            return '{}-{}'.format(self.name, _version) in self.vc.parent_tags(self.vc_dir)
        else:
            return self.vc.is_release_from_tags(self.vc_dir, self.name)

    def release_version(self, snapshotSuffix='dev'):
        """
        Gets the release tag from VC or create a time based once if VC is unavailable
        """
        if snapshotSuffix not in self._releaseVersion:
            _version = self._get_early_suite_dict_property('version')
            if _version and self.getMxCompatibility().addVersionSuffixToExplicitVersion():
                if not self.is_release():
                    _version = _version + '-' + snapshotSuffix
            if not _version:
                _version = self.vc.release_version_from_tags(self.vc_dir, self.name, snapshotSuffix=snapshotSuffix)
            if not _version:
                _version = 'unknown-{0}-{1}'.format(platform.node(), time.strftime('%Y-%m-%d_%H-%M-%S_%Z'))
            self._releaseVersion[snapshotSuffix] = _version
        return self._releaseVersion[snapshotSuffix]

    def scm_metadata(self, abortOnError=False):
        scm = self.scm
        if scm:
            return scm
        pull = self.vc.default_pull(self.vc_dir, abortOnError=abortOnError)
        if abortOnError and not pull:
            abort("Can not find scm metadata for suite {0} ({1})".format(self.name, self.vc_dir))
        push = self.vc.default_push(self.vc_dir, abortOnError=abortOnError)
        if not push:
            push = pull
        return SCMMetadata(pull, pull, push)

    def _load_metadata(self):
        super(SourceSuite, self)._load_metadata()
        self._load_projects()
        if hasattr(self, 'mx_register_dynamic_suite_constituents'):
            def _register_project(proj):
                self.projects.append(proj)

            def _register_distribution(dist):
                self.dists.append(dist)
            self.mx_register_dynamic_suite_constituents(_register_project, _register_distribution)
        self._finish_load_projects()

    def _load_projects(self):
        """projects are unique to source suites"""
        projsMap = self._check_suiteDict('projects')

        for name, attrs in sorted(projsMap.items()):
            try:
                context = 'project ' + name
                className = attrs.pop('class', None)
                theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
                os_arch = Suite._pop_os_arch(attrs, context)
                Suite._merge_os_arch_attrs(attrs, os_arch, context)
                deps = Suite._pop_list(attrs, 'dependencies', context)
                genDeps = Suite._pop_list(attrs, 'generatedDependencies', context)
                if genDeps:
                    deps += genDeps
                    # Re-add generatedDependencies attribute so it can be used in canonicalizeprojects
                    attrs['generatedDependencies'] = genDeps
                workingSets = attrs.pop('workingSets', None)
                jlintOverrides = attrs.pop('lint.overrides', None)
                if className:
                    if not self.extensions or not hasattr(self.extensions, className):
                        abort('Project {} requires a custom class ({}) which was not found in {}'.format(name, className, join(self.mxDir, self._extensions_name() + '.py')))
                    p = getattr(self.extensions, className)(self, name, deps, workingSets, theLicense=theLicense, **attrs)
                else:
                    srcDirs = Suite._pop_list(attrs, 'sourceDirs', context)
                    projectDir = attrs.pop('dir', None)
                    subDir = attrs.pop('subDir', None)
                    if projectDir:
                        d = join(self.dir, projectDir)
                    elif subDir is None:
                        d = join(self.dir, name)
                    else:
                        d = join(self.dir, subDir, name)
                    native = attrs.pop('native', False)

                    old_test_project = attrs.pop('isTestProject', None)
                    if old_test_project is not None:
                        abort_or_warn("`isTestProject` attribute has been renamed to `testProject`", self.getMxCompatibility().deprecateIsTestProject(), context)
                    testProject = attrs.pop('testProject', old_test_project)

                    if native:
                        if isinstance(native, bool) or native.lower() == "true":
                            output = attrs.pop('output', None)
                            results = Suite._pop_list(attrs, 'results', context)
                            p = NativeProject(self, name, subDir, srcDirs, deps, workingSets, results, output, d,
                                              theLicense=theLicense, testProject=testProject, **attrs)
                        else:
                            from mx_native import DefaultNativeProject
                            p = DefaultNativeProject(self, name, subDir, srcDirs, deps, workingSets, d, kind=native,
                                                     theLicense=theLicense, testProject=testProject, **attrs)
                    else:
                        javaCompliance = attrs.pop('javaCompliance', None)
                        if javaCompliance is None:
                            abort('javaCompliance property required for non-native project ' + name)
                        p = JavaProject(self, name, subDir, srcDirs, deps, javaCompliance, workingSets, d, theLicense=theLicense, testProject=testProject, **attrs)
                        p.checkstyleProj = attrs.pop('checkstyle', name)
                        if p.checkstyleProj != name and 'checkstyleVersion' in attrs:
                            compat = self.getMxCompatibility()
                            should_abort = compat.check_checkstyle_config()
                            abort_or_warn('Cannot specify both "checkstyle and "checkstyleVersion" attribute', should_abort, context=p)
                        p.checkPackagePrefix = attrs.pop('checkPackagePrefix', 'true') == 'true'
                        ap = Suite._pop_list(attrs, 'annotationProcessors', context)
                        if ap:
                            p.declaredAnnotationProcessors = ap
                        if jlintOverrides:
                            p._javac_lint_overrides = jlintOverrides
                        if hasattr(p, "javaVersionExclusion") and self.getMxCompatibility().supports_disjoint_JavaCompliance_range():
                            abort('The "javaVersionExclusion" is no longer supported. Use a disjoint range for the "javaCompliance" attribute instead (e.g. "8,13+")', context=p)
                if self.getMxCompatibility().overwriteProjectAttributes():
                    p.__dict__.update(attrs)
                else:
                    for k, v in attrs.items():
                        if not hasattr(p, k):
                            setattr(p, k, v)
                self.projects.append(p)
            except:
                log_error("Error while creating project {}".format(name))
                raise

    def _finish_load_projects(self):
        # Record the projects that define annotation processors
        apProjects = {}
        for p in self.projects:
            if not p.isJavaProject():
                continue
            annotationProcessors = None
            for srcDir in p.source_dirs():
                configFile = join(srcDir, 'META-INF', 'services', 'javax.annotation.processing.Processor')
                if exists(configFile):
                    with open(configFile) as fp:
                        annotationProcessors = [ap.strip() for ap in fp]
                        if len(annotationProcessors) != 0 and p.checkPackagePrefix:
                            for ap in annotationProcessors:
                                if not ap.startswith(p.name):
                                    abort(ap + ' in ' + configFile + ' does not start with ' + p.name)
            if annotationProcessors:
                p.definedAnnotationProcessors = annotationProcessors
                apProjects[p.name] = p

        # Initialize the definedAnnotationProcessors list for distributions with direct
        # dependencies on projects that define one or more annotation processors.
        for dist in self.dists:
            aps = []
            for dep in dist.deps:
                name = dep if isinstance(dep, str) else dep.name
                if name in apProjects:
                    aps += apProjects[name].definedAnnotationProcessors
            if aps:
                dist.definedAnnotationProcessors = aps
                # Restrict exported annotation processors to those explicitly defined by the projects
                def _refineAnnotationProcessorServiceConfig(dist):
                    apsJar = dist.path
                    config = 'META-INF/services/javax.annotation.processing.Processor'
                    currentAps = None
                    with zipfile.ZipFile(apsJar, 'r') as zf:
                        if config in zf.namelist():
                            currentAps = zf.read(config).split()
                    # Overwriting of open files doesn't work on Windows, so now that
                    # `apsJar` is closed we can safely overwrite it if necessary
                    if currentAps is not None and currentAps != dist.definedAnnotationProcessors:
                        logv('[updating ' + config + ' in ' + apsJar + ']')
                        with Archiver(apsJar) as arc:
                            with zipfile.ZipFile(apsJar, 'r') as lp:
                                for arcname in lp.namelist():
                                    if arcname == config:
                                        arc.zf.writestr(arcname, '\n'.join(dist.definedAnnotationProcessors) + '\n')
                                    else:
                                        arc.zf.writestr(arcname, lp.read(arcname))
                dist.add_update_listener(_refineAnnotationProcessorServiceConfig)

    @staticmethod
    def _load_env_in_mxDir(mxDir, env=None, file_name='env', abort_if_missing=False):
        e = join(mxDir, file_name)
        SourceSuite._load_env_file(e, env, abort_if_missing=abort_if_missing)

    @staticmethod
    def _load_env_file(e, env=None, abort_if_missing=False):
        if exists(e):
            with open(e) as f:
                lineNum = 0
                for line in f:
                    lineNum = lineNum + 1
                    line = line.strip()
                    if len(line) != 0 and line[0] != '#':
                        if not '=' in line:
                            abort(e + ':' + str(lineNum) + ': line does not match pattern "key=value"')
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = expandvars_in_property(value.strip())
                        if env is None:
                            os.environ[key] = value
                            logv('Setting environment variable %s=%s from %s' % (key, value, e))
                        else:
                            env[key] = value
                            logv('Read variable %s=%s from %s' % (key, value, e))
        elif abort_if_missing:
            abort("Could not find env file: {}".format(e))

    def _parse_env(self):
        SourceSuite._load_env_in_mxDir(self.mxDir, _loadedEnv)

    def _register_metadata(self):
        Suite._register_metadata(self)
        for p in self.projects:
            existing = _projects.get(p.name)
            if existing is not None and _check_global_structures:
                abort('cannot override project {} in {} with project of the same name in {}'.format(p.name, existing.dir, p.dir))
            if not hasattr(_opts, 'ignored_projects') or not p.name in _opts.ignored_projects:
                _projects[p.name] = p
            # check all project dependencies are local
            for d in p.deps:
                dp = project(d, False)
                if dp:
                    if not dp in self.projects:
                        dists = [(dist.suite.name + ':' + dist.name) for dist in dp.suite.dists if dp in dist.archived_deps()]
                        if len(dists) > 1:
                            dists = ', '.join(dists[:-1]) + ' or ' + dists[-1]
                        elif dists:
                            dists = dists[0]
                        else:
                            dists = '<name of distribution containing ' + dp.name + '>'
                        p.abort("dependency to project '{}' defined in an imported suite must use {} instead".format(dp.name, dists))
                    elif dp == p:
                        p.abort("recursive dependency in suite '{}' in project '{}'".format(self.name, d))

    @staticmethod
    def _projects_recursive(importing_suite, imported_suite, projects, visitmap):
        if imported_suite.name in visitmap:
            return
        projects += imported_suite.projects
        visitmap[imported_suite.name] = True
        imported_suite.visit_imports(importing_suite._projects_recursive_visitor, projects=projects, visitmap=visitmap)

    @staticmethod
    def _projects_recursive_visitor(importing_suite, suite_import, projects, visitmap, **extra_args):
        if isinstance(importing_suite, SourceSuite):
            importing_suite._projects_recursive(importing_suite, suite(suite_import.name), projects, visitmap)

    def projects_recursive(self):
        """return all projects including those in imported suites"""
        result = []
        result += self.projects
        visitmap = dict()
        self.visit_imports(self._projects_recursive_visitor, projects=result, visitmap=visitmap,)
        return result

    def mx_binary_distribution_jar_path(self):
        """
        returns the absolute path of the mx binary distribution jar.
        """
        return join(self.dir, _mx_binary_distribution_jar(self.name))

    def create_mx_binary_distribution_jar(self):
        """
        Creates a jar file named name-mx.jar that contains
        the metadata for another suite to import this suite as a BinarySuite.
        TODO check timestamps to avoid recreating this repeatedly, or would
        the check dominate anyway?
        TODO It would be cleaner for subsequent loading if we actually wrote a
        transformed suite.py file that only contained distribution info, to
        detect access to private (non-distribution) state
        """
        mxMetaJar = self.mx_binary_distribution_jar_path()
        mxfiles = glob.glob(join(self.mxDir, '*.py'))
        mxfiles += glob.glob(join(self.mxDir, '*.properties'))
        with Archiver(mxMetaJar) as arc:
            for mxfile in mxfiles:
                mxDirBase = basename(self.mxDir)
                arc.zf.write(mxfile, arcname=join(mxDirBase, basename(mxfile)))

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        esdict = {}
        # start with the mxtool defaults
        defaultEclipseSettingsDir = join(_mx_suite.dir, 'eclipse-settings')
        if exists(defaultEclipseSettingsDir):
            for name in os.listdir(defaultEclipseSettingsDir):
                esdict[name] = [os.path.abspath(join(defaultEclipseSettingsDir, name))]

        # append suite overrides
        eclipseSettingsDir = join(self.mxDir, 'eclipse-settings')
        if exists(eclipseSettingsDir):
            for name in os.listdir(eclipseSettingsDir):
                esdict.setdefault(name, []).append(os.path.abspath(join(eclipseSettingsDir, name)))
        return esdict

    def netbeans_settings_sources(self):
        """
        Gets a dictionary from the name of an NetBeans settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        esdict = {}
        # start with the mxtool defaults
        defaultNetBeansSuiteDir = join(_mx_suite.dir, 'netbeans-settings')
        if exists(defaultNetBeansSuiteDir):
            for name in os.listdir(defaultNetBeansSuiteDir):
                esdict[name] = [os.path.abspath(join(defaultNetBeansSuiteDir, name))]

        # append suite overrides
        netBeansSettingsDir = join(self.mxDir, 'netbeans-settings')
        if exists(netBeansSettingsDir):
            for name in os.listdir(netBeansSettingsDir):
                esdict.setdefault(name, []).append(os.path.abspath(join(netBeansSettingsDir, name)))
        return esdict

"""
A pre-built suite downloaded from a Maven repository.
"""
class BinarySuite(Suite):
    def __init__(self, mxDir, importing_suite, dynamicallyImported=False, load=True):
        Suite.__init__(self, mxDir, False, False, importing_suite, load, BinaryVC(), dirname(mxDir), dynamicallyImported=dynamicallyImported)
        # At this stage the suite directory is guaranteed to exist as is the mx.suitname
        # directory. For a freshly downloaded suite, the actual distribution jars
        # have not been downloaded as we need info from the suite.py for that

    def _load(self):
        self._load_binary_suite()
        super(BinarySuite, self)._load()

    def reload_binary_suite(self):
        for d in self.dists:
            _dists.pop(d.name, None)
        self.dists = []
        self._load_binary_suite()

    def version(self, abortOnError=True):
        """
        Return the current head changeset of this suite.
        """
        # we do not cache the version because it changes in development
        return self.vc.parent(self.vc_dir)

    def release_version(self):
        return self.version()

    def isDirty(self, abortOnError=True):
        # a binary suite can not be dirty
        return False

    def _load_binary_suite(self):
        """
        Always load the suite.py file and the distribution info defined there,
        download the jar files for a freshly cloned suite
        """
        self._load_suite_dict()
        Suite._load_distributions(self, self._check_suiteDict('distributions'))

    def _load_libraries(self, libsMap):
        super(BinarySuite, self)._load_libraries(libsMap)
        for l in self.libs:
            if l.isLibrary() or l.isResourceLibrary():
                l.get_path(resolve=True)
            if l.isLibrary():
                l.get_source_path(resolve=True)

    def _parse_env(self):
        pass

    def _load_distributions(self, distsMap):
        # This gets done explicitly in _load_binary_suite as we need the info there
        # so, in that mode, we don't want to call the superclass method again
        pass

    def _load_metadata(self):
        super(BinarySuite, self)._load_metadata()
        if hasattr(self, 'mx_register_dynamic_suite_constituents'):
            def _register_distribution(dist):
                self.dists.append(dist)
            self.mx_register_dynamic_suite_constituents(None, _register_distribution)

    def _load_distribution(self, name, attrs):
        ret = super(BinarySuite, self)._load_distribution(name, attrs)
        ret.post_init()
        self.vc.getDistribution(self.dir, ret)
        return ret

    def _register_metadata(self):
        # since we are working with the original suite.py file, we remove some
        # values that should not be visible
        self.projects = []
        Suite._register_metadata(self)

    def _resolve_dependencies(self):
        super(BinarySuite, self)._resolve_dependencies()
        # Remove projects from dist dependencies
        for d in self.dists:
            d.deps = [dep for dep in d.deps if dep and not dep.isJavaProject()]


class InternalSuite(SourceSuite):
    def __init__(self, mxDir):
        mxMxDir = _is_suite_dir(mxDir)
        assert mxMxDir
        SourceSuite.__init__(self, mxMxDir, internal=True)
        _register_suite(self)


class MXSuite(InternalSuite):
    def __init__(self):
        InternalSuite.__init__(self, _mx_home)

    def _parse_env(self):
        # Only load the env file from mx when it's the primary suite.  This can only
        # be determined when the primary suite has been set so it must be deferred but
        # since the primary suite env should be loaded last this should be ok.
        def _deferrable():
            assert primary_suite()
            if self == primary_suite():
                SourceSuite._load_env_in_mxDir(self.mxDir)
        _primary_suite_deferrables.append(_deferrable)


class MXTestsSuite(InternalSuite):
    def __init__(self):
        InternalSuite.__init__(self, join(_mx_home, "tests"))


def suites(opt_limit_to_suite=False, includeBinary=True, include_mx=False):
    """
    Get the list of all loaded suites.
    """
    res = [s for s in _suites.values() if not s.internal and (includeBinary or isinstance(s, SourceSuite))]
    if include_mx:
        res.append(_mx_suite)
    if opt_limit_to_suite and _opts.specific_suites:
        res = [s for s in res if s.name in _opts.specific_suites]
    return res


def suite(name, fatalIfMissing=True, context=None):
    """
    Get the suite for a given name.
    :rtype: Suite
    """
    s = _suites.get(name)
    if s is None and fatalIfMissing:
        abort('suite named ' + name + ' not found', context=context)
    return s


def primary_or_specific_suites():
    """:rtype: list[Suite]"""
    if _opts.specific_suites:
        return [suite(name) for name in _opts.specific_suites]
    return [primary_suite()]

def _suitename(mxDir):
    parts = basename(mxDir).split('.')
    if len(parts) == 3:
        assert parts[0] == ''
        assert parts[1] == 'mx'
        return parts[2]
    assert len(parts) == 2, parts
    assert parts[0] == 'mx'
    return parts[1]

def _is_suite_dir(d, mxDirName=None):
    """
    Checks if d contains a suite.
    If mxDirName is None, matches any suite name, otherwise checks for exactly `mxDirName` or `mxDirName` with a ``.`` prefix.
    """
    if os.path.isdir(d):
        for f in [mxDirName, '.' + mxDirName] if mxDirName else [e for e in os.listdir(d) if e.startswith('mx.') or e.startswith('.mx.')]:
            mxDir = join(d, f)
            if exists(mxDir) and isdir(mxDir) and (exists(join(mxDir, 'suite.py'))):
                return mxDir


def _findPrimarySuiteMxDirFrom(d):
    """ search for a suite directory upwards from 'd' """
    while d:
        mxDir = _is_suite_dir(d)
        if mxDir is not None:
            return mxDir
        parent = dirname(d)
        if d == parent:
            return None
        d = parent

    return None

def _findPrimarySuiteMxDir():
    # check for explicit setting
    if _primary_suite_path is not None:
        mxDir = _is_suite_dir(_primary_suite_path)
        if mxDir is not None:
            return mxDir
        else:
            abort(_primary_suite_path + ' does not contain an mx suite')

    # try current working directory first
    mxDir = _findPrimarySuiteMxDirFrom(os.getcwd())
    if mxDir is not None:
        return mxDir
    return None


def _register_suite(s):
    assert s.name not in _suites, s.name
    _suites[s.name] = s


def _use_binary_suite(suite_name):
    return _binary_suites is not None and (len(_binary_suites) == 0 or suite_name in _binary_suites)


def _find_suite_import(importing_suite, suite_import, fatalIfMissing=True, load=True, clone_binary_first=False):
    """
    :rtype : (Suite | None, bool)
    """
    search_mode = 'binary' if _use_binary_suite(suite_import.name) else 'source'
    clone_mode = 'binary' if clone_binary_first else search_mode

    def _find_suite_dir(mode):
        """
        Attempts to locate an existing suite in the local context
        Returns the path to the mx.name dir if found else None
        """
        if mode == 'binary':
            # binary suites are always stored relative to the importing suite in mx-private directory
            return importing_suite._find_binary_suite_dir(suite_import.name)
        else:
            # use the SuiteModel to locate a local source copy of the suite
            return _suitemodel.find_suite_dir(suite_import)

    def _get_import_dir(url, mode):
        """Return directory where the suite will be cloned to"""
        if mode == 'binary':
            return importing_suite.binary_suite_dir(suite_import.name)
        else:
            # Try use the URL first so that a big repo is cloned to a local
            # directory whose named is based on the repo instead of a suite
            # nested in the big repo.
            root, _ = os.path.splitext(basename(_urllib_parse.urlparse(url).path))
            if root:
                import_dir = join(SiblingSuiteModel.siblings_dir(importing_suite.dir), root)
            else:
                import_dir, _ = _suitemodel.importee_dir(importing_suite.dir, suite_import, check_alternate=False)
            if exists(import_dir):
                abort("Suite import directory ({0}) for suite '{1}' exists but no suite definition could be found.".format(import_dir, suite_import.name))
            return import_dir

    def _clone_kwargs(mode):
        if mode == 'binary':
            return dict(result=dict(), suite_name=suite_import.name)
        else:
            return dict()

    _clone_status = [False]
    _found_mode = [None]

    def _find_or_clone():
        _import_mx_dir = _find_suite_dir(search_mode)
        if _import_mx_dir is not None:
            _found_mode[0] = search_mode
            return _import_mx_dir
        if clone_mode != search_mode:
            _import_mx_dir = _find_suite_dir(clone_mode)
        if _import_mx_dir is None:
            # No local copy, so use the URLs in order to "download" one
            clone_kwargs = _clone_kwargs(clone_mode)
            for urlinfo in suite_import.urlinfos:
                if urlinfo.abs_kind() != clone_mode or not urlinfo.vc.check(abortOnError=False):
                    continue
                import_dir = _get_import_dir(urlinfo.url, clone_mode)
                if exists(import_dir):
                    warn("Trying to clone suite '{suite_name}' but directory {import_dir} already exists and does not seem to contain suite {suite_name}".format(suite_name=suite_import.name, import_dir=import_dir))
                    continue
                if urlinfo.vc.clone(urlinfo.url, import_dir, suite_import.version, abortOnError=False, **clone_kwargs):
                    _import_mx_dir = _find_suite_dir(clone_mode)
                    if _import_mx_dir is None:
                        warn("Cloned suite '{suite_name}' but the result ({import_dir}) does not seem to contain suite {suite_name}".format(suite_name=suite_import.name, import_dir=import_dir))
                    else:
                        _clone_status[0] = True
                        break
                else:
                    # it is possible that the clone partially populated the target
                    # which will mess up further attempts, so we "clean" it
                    if exists(import_dir):
                        shutil.rmtree(import_dir)
        if _import_mx_dir is not None:
            _found_mode[0] = clone_mode
        return _import_mx_dir

    import_mx_dir = _find_or_clone()

    if import_mx_dir is None:
        if clone_mode == 'binary':
            if search_mode != 'source' or any((urlinfo.abs_kind() == 'source' for urlinfo in suite_import.urlinfos)):
                warn("Binary import suite '{0}' not found, falling back to source dependency".format(suite_import.name))
            search_mode = 'source'
            clone_mode = 'source'
            import_mx_dir = _find_or_clone()
        elif all(urlinfo.abs_kind() == 'binary' for urlinfo in suite_import.urlinfos):
            logv("Import suite '{0}' has no source urls, falling back to binary dependency".format(suite_import.name))
            search_mode = 'binary'
            clone_mode = 'binary'
            import_mx_dir = _find_or_clone()

    if import_mx_dir is None:
        if fatalIfMissing:
            suffix = ''
            if _use_binary_suite(suite_import.name) and not any((urlinfo.abs_kind() == 'binary' for urlinfo in suite_import.urlinfos)):
                suffix = " No binary URLs in {} for import of '{}' into '{}'.".format(importing_suite.suite_py(), suite_import.name, importing_suite.name)
            abort("Imported suite '{}' not found (binary or source).{}".format(suite_import.name, suffix))
        else:
            return None, False

    # Factory method?
    if _found_mode[0] == 'binary':
        return BinarySuite(import_mx_dir, importing_suite=importing_suite, load=load, dynamicallyImported=suite_import.dynamicImport), _clone_status[0]
    else:
        assert _found_mode[0] == 'source'
        return SourceSuite(import_mx_dir, importing_suite=importing_suite, load=load, dynamicallyImported=suite_import.dynamicImport), _clone_status[0]


def _discover_suites(primary_suite_dir, load=True, register=True, update_existing=False):

    def _log_discovery(msg):
        dt = datetime.utcnow() - _mx_start_datetime
        logvv(str(dt) + colorize(" [suite-discovery] ", color='green', stream=sys.stdout) + msg)
    _log_discovery("Starting discovery with primary dir " + primary_suite_dir)
    primary = SourceSuite(primary_suite_dir, load=False, primary=True)
    _suitemodel.set_primary_dir(primary.dir)
    primary._register_url_rewrites()
    discovered = {}
    ancestor_names = {}
    importer_names = {}
    original_version = {}
    vc_dir_to_suite_names = {}
    versions_from = {}


    class VersionType:
        CLONED = 0
        REVISION = 1
        BRANCH = 2

    worklist = deque()

    def _add_discovered_suite(_discovered_suite, first_importing_suite_name):
        if first_importing_suite_name:
            importer_names[_discovered_suite.name] = {first_importing_suite_name}
            ancestor_names[_discovered_suite.name] = {first_importing_suite_name} | ancestor_names[first_importing_suite_name]
        else:
            assert _discovered_suite == primary
            importer_names[_discovered_suite.name] = frozenset()
            ancestor_names[primary.name] = frozenset()
        for _suite_import in _discovered_suite.suite_imports:
            if _discovered_suite.name == _suite_import.name:
                abort("Error: suite '{}' imports itself".format(_discovered_suite.name))
            _log_discovery("Adding {discovered} -> {imported} in worklist after discovering {discovered}".format(discovered=_discovered_suite.name, imported=_suite_import.name))
            worklist.append((_discovered_suite.name, _suite_import.name))
        if _discovered_suite.vc_dir:
            vc_dir_to_suite_names.setdefault(_discovered_suite.vc_dir, set()).add(_discovered_suite.name)
        discovered[_discovered_suite.name] = _discovered_suite

    _add_discovered_suite(primary, None)

    def _is_imported_by_primary(_discovered_suite):
        for _suite_name in vc_dir_to_suite_names[_discovered_suite.vc_dir]:
            if primary.name == _suite_name:
                return True
            if primary.name in importer_names[_suite_name]:
                assert primary.get_import(_suite_name), primary.name + ' ' + _suite_name
                if not primary.get_import(_suite_name).dynamicImport:
                    return True
        return False

    def _clear_pyc_files(_updated_suite):
        if _updated_suite.vc_dir in vc_dir_to_suite_names:
            suites_to_clean = set((discovered[name] for name in vc_dir_to_suite_names[_updated_suite.vc_dir]))
        else:
            suites_to_clean = set()
        suites_to_clean.add(_updated_suite)
        for collocated_suite in suites_to_clean:
            pyc_file = collocated_suite.suite_py() + 'c'
            if exists(pyc_file):
                os.unlink(pyc_file)

    def _was_cloned_or_updated_during_discovery(_discovered_suite):
        return _discovered_suite.vc_dir is not None and _discovered_suite.vc_dir in original_version

    def _update_repo(_discovered_suite, update_version, forget=False, update_reason="to resolve conflict"):
        current_version = _discovered_suite.vc.parent(_discovered_suite.vc_dir)
        if _discovered_suite.vc_dir not in original_version:
            branch = _discovered_suite.vc.active_branch(_discovered_suite.vc_dir, abortOnError=False)
            if branch is not None:
                original_version[_discovered_suite.vc_dir] = VersionType.BRANCH, branch
            else:
                original_version[_discovered_suite.vc_dir] = VersionType.REVISION, current_version
        if current_version == update_version:
            return False
        _discovered_suite.vc.update(_discovered_suite.vc_dir, rev=update_version, mayPull=True)
        _clear_pyc_files(_discovered_suite)
        if forget:
            # we updated, this may change the DAG so
            # "un-discover" anything that was discovered based on old information
            _log_discovery("Updated needed {}: updating {} to {}".format(update_reason, _discovered_suite.vc_dir, update_version))
            forgotten_edges = {}

            def _forget_visitor(_, __suite_import):
                _forget_suite(__suite_import.name)

            def _forget_suite(suite_name):
                if suite_name not in discovered:
                    return
                _log_discovery("Forgetting {} after update".format(suite_name))
                if suite_name in ancestor_names:
                    del ancestor_names[suite_name]
                if suite_name in importer_names:
                    for importer_name in importer_names[suite_name]:
                        forgotten_edges.setdefault(importer_name, set()).add(suite_name)
                    del importer_names[suite_name]
                if suite_name in discovered:
                    s = discovered[suite_name]
                    del discovered[suite_name]
                    s.visit_imports(_forget_visitor)
                for suite_names in vc_dir_to_suite_names.values():
                    suite_names.discard(suite_name)
                new_worklist = [(_f, _t) for _f, _t in worklist if _f != suite_name]
                worklist.clear()
                worklist.extend(new_worklist)
                new_versions_from = {_s: (_f, _i) for _s, (_f, _i) in versions_from.items() if _i != suite_name}
                versions_from.clear()
                versions_from.update(new_versions_from)
                if suite_name in forgotten_edges:
                    del forgotten_edges[suite_name]

            for _collocated_suite_name in list(vc_dir_to_suite_names[_discovered_suite.vc_dir]):
                _forget_suite(_collocated_suite_name)
            # Add all the edges that need re-resolution
            for __importing_suite, imported_suite_set in forgotten_edges.items():
                for imported_suite in imported_suite_set:
                    _log_discovery("Adding {} -> {} in worklist after conflict".format(__importing_suite, imported_suite))
                    worklist.appendleft((__importing_suite, imported_suite))
        else:
            _discovered_suite.re_init_imports()
        return True

    # This is used to honor the "version_from" directives. Note that we only reach here if the importer is in a different repo.
    # 1. we may only ignore an edge that points to a suite that has a "version_from", or to an ancestor of such a suite
    # 2. we do not ignore an edge if the importer is one of the "from" suites (a suite that is designated by a "version_from" of an other suite)
    # 3. otherwise if the edge points directly some something that has a "version_from", we ignore it for sure
    # 4. and finally, we do not ignore edges that point to a "from" suite or its ancestor in the repo
    # This give the suite mentioned in "version_from" priority
    def _should_ignore_conflict_edge(_imported_suite, _importer_name):
        vc_suites = vc_dir_to_suite_names[_imported_suite.vc_dir]
        for suite_with_from, (from_suite, _) in versions_from.items():
            if suite_with_from not in vc_suites:
                continue
            suite_with_from_and_ancestors = {suite_with_from}
            suite_with_from_and_ancestors |= vc_suites & ancestor_names[suite_with_from]
            if _imported_suite.name in suite_with_from_and_ancestors:  # 1. above
                if _importer_name != from_suite:  # 2. above
                    if _imported_suite.name == suite_with_from:  # 3. above
                        _log_discovery("Ignoring {} -> {} because of version_from({}) = {} (fast-path)".format(_importer_name, _imported_suite.name, suite_with_from, from_suite))
                        return True
                    if from_suite not in ancestor_names:
                        _log_discovery("Temporarily ignoring {} -> {} because of version_from({}) = {f_suite} ({f_suite} is not yet discovered)".format(_importer_name, _imported_suite.name, suite_with_from, f_suite=from_suite))
                        return True
                    vc_from_suite_and_ancestors = {from_suite}
                    vc_from_suite_and_ancestors |= vc_suites & ancestor_names[from_suite]
                    if _imported_suite.name not in vc_from_suite_and_ancestors:  # 4. above
                        _log_discovery("Ignoring {} -> {} because of version_from({}) = {}".format(_importer_name, _imported_suite.name, suite_with_from, from_suite))
                        return True
        return False

    def _check_and_handle_version_conflict(_suite_import, _importing_suite, _discovered_suite):
        if _importing_suite.vc_dir == _discovered_suite.vc_dir:
            return True
        if _is_imported_by_primary(_discovered_suite):
            _log_discovery("Re-reached {} from {}, nothing to do (imported by primary)".format(_suite_import.name, importing_suite.name))
            return True
        if _should_ignore_conflict_edge(_discovered_suite, _importing_suite.name):
            return True
        # check that all other importers use the same version
        for collocated_suite_name in vc_dir_to_suite_names[_discovered_suite.vc_dir]:
            for other_importer_name in importer_names[collocated_suite_name]:
                if other_importer_name == _importing_suite.name:
                    continue
                if _should_ignore_conflict_edge(_discovered_suite, other_importer_name):
                    continue
                other_importer = discovered[other_importer_name]
                other_importers_import = other_importer.get_import(collocated_suite_name)
                if other_importers_import.version and _suite_import.version and other_importers_import.version != _suite_import.version:
                    # conflict, try to resolve it
                    if _suite_import.name == collocated_suite_name:
                        _log_discovery("Re-reached {} from {} with conflicting version compared to {}".format(collocated_suite_name, _importing_suite.name, other_importer_name))
                    else:
                        _log_discovery("Re-reached {} (collocated with {}) from {} with conflicting version compared to {}".format(collocated_suite_name, _suite_import.name, _importing_suite.name, other_importer_name))
                    if update_existing or _was_cloned_or_updated_during_discovery(_discovered_suite):
                        resolved = _resolve_suite_version_conflict(_discovered_suite.name, _discovered_suite, other_importers_import.version, other_importer, _suite_import, _importing_suite)
                        if resolved and _update_repo(_discovered_suite, resolved, forget=True):
                            return False
                    else:
                        # This suite was already present
                        resolution = _resolve_suite_version_conflict(_discovered_suite.name, _discovered_suite, other_importers_import.version, other_importer, _suite_import, _importing_suite, dry_run=True)
                        if resolution is not None:
                            if _suite_import.name == collocated_suite_name:
                                warn("{importing} and {other_import} import different versions of {conflicted}: {version} vs. {other_version}".format(
                                    conflicted=collocated_suite_name,
                                    importing=_importing_suite.name,
                                    other_import=other_importer_name,
                                    version=_suite_import.version,
                                    other_version=other_importers_import.version
                                ))
                            else:
                                warn("{importing} and {other_import} import different versions of {conflicted} (collocated with {conflicted_src}): {version} vs. {other_version}".format(
                                    conflicted=collocated_suite_name,
                                    conflicted_src=_suite_import.name,
                                    importing=_importing_suite.name,
                                    other_import=other_importer_name,
                                    version=_suite_import.version,
                                    other_version=other_importers_import.version
                                ))
                else:
                    if _suite_import.name == collocated_suite_name:
                        _log_discovery("Re-reached {} from {} with same version as {}".format(collocated_suite_name, _importing_suite.name, other_importer_name))
                    else:
                        _log_discovery("Re-reached {} (collocated with {}) from {} with same version as {}".format(collocated_suite_name, _suite_import.name, _importing_suite.name, other_importer_name))
        return True

    try:
        dynamic_imports_added = [False]

        def _maybe_add_dynamic_imports():
            if not worklist and not dynamic_imports_added[0]:
                for name, in_subdir in get_dynamic_imports():
                    if name not in discovered:
                        primary.suite_imports.append(SuiteImport(name, version=None, urlinfos=None, dynamicImport=True, in_subdir=in_subdir))
                        worklist.append((primary.name, name))
                        _log_discovery("Adding {}->{} dynamic import".format(primary.name, name))
                    else:
                        _log_discovery("Skipping {}->{} dynamic import (already imported)".format(primary.name, name))
                dynamic_imports_added[0] = True

        _maybe_add_dynamic_imports()
        while worklist:
            importing_suite_name, imported_suite_name = worklist.popleft()
            importing_suite = discovered[importing_suite_name]
            suite_import = importing_suite.get_import(imported_suite_name)
            if suite_import.version_from:
                if imported_suite_name not in versions_from:
                    versions_from[imported_suite_name] = suite_import.version_from, importing_suite_name
                    _log_discovery("Setting 'version_from({imported}, {from_suite})' as requested by {importing}".format(
                        importing=importing_suite_name, imported=imported_suite_name, from_suite=suite_import.version_from))
                elif suite_import.version_from != versions_from[imported_suite_name][0]:
                    _log_discovery("Ignoring 'version_from({imported}, {from_suite})' directive from {importing} because we already have 'version_from({imported}, {previous_from_suite})' from {previous_importing}".format(
                        importing=importing_suite_name, imported=imported_suite_name, from_suite=suite_import.version_from,
                        previous_importing=versions_from[imported_suite_name][1], previous_from_suite=versions_from[imported_suite_name][0]))
            elif suite_import.name in discovered:
                if suite_import.name in ancestor_names[importing_suite.name]:
                    abort("Import cycle detected: {importer} imports {importee} but {importee} transitively imports {importer}".format(importer=importing_suite.name, importee=suite_import.name))
                discovered_suite = discovered[suite_import.name]
                assert suite_import.name in vc_dir_to_suite_names[discovered_suite.vc_dir]
                # Update importer data after re-reaching
                importer_names[suite_import.name].add(importing_suite.name)
                ancestor_names[suite_import.name] |= ancestor_names[importing_suite.name]
                _check_and_handle_version_conflict(suite_import, importing_suite, discovered_suite)
            else:
                discovered_suite, is_clone = _find_suite_import(importing_suite, suite_import, load=False)
                _log_discovery("Discovered {} from {} ({}, newly cloned: {})".format(discovered_suite.name, importing_suite_name, discovered_suite.dir, is_clone))
                if is_clone:
                    original_version[discovered_suite.vc_dir] = VersionType.CLONED, None
                    _add_discovered_suite(discovered_suite, importing_suite.name)
                elif discovered_suite.vc_dir in vc_dir_to_suite_names and not vc_dir_to_suite_names[discovered_suite.vc_dir]:
                    # we re-discovered a suite that we had cloned and then "un-discovered".
                    _log_discovery("This is a re-discovery of a previously forgotten repo: {}. Leaving it as-is".format(discovered_suite.vc_dir))
                    _add_discovered_suite(discovered_suite, importing_suite.name)
                elif _was_cloned_or_updated_during_discovery(discovered_suite):
                    # we are re-reaching a repo through a different imported suite
                    _add_discovered_suite(discovered_suite, importing_suite.name)
                    _check_and_handle_version_conflict(suite_import, importing_suite, discovered_suite)
                elif (update_existing or discovered_suite.isBinarySuite()) and suite_import.version:
                    _add_discovered_suite(discovered_suite, importing_suite.name)
                    if _update_repo(discovered_suite, suite_import.version, forget=True, update_reason="(update_existing mode)"):
                        actual_version = discovered_suite.vc.parent(discovered_suite.vc_dir)
                        if actual_version != suite_import.version:
                            warn("Failed to update {} (in {}) to version {}! Leaving it at {}.".format(discovered_suite.name, discovered_suite.vc_dir, suite_import.version, actual_version))
                        else:
                            _log_discovery("Updated {} after discovery (`update_existing` mode) to {}".format(discovered_suite.vc_dir, suite_import.version))
                    else:
                        _log_discovery("{} was already at the right revision: {} (`update_existing` mode)".format(discovered_suite.vc_dir, suite_import.version))
                else:
                    _add_discovered_suite(discovered_suite, importing_suite.name)
            _maybe_add_dynamic_imports()
    except SystemExit as se:
        cloned_during_discovery = [d for d, (t, _) in original_version.items() if t == VersionType.CLONED]
        if cloned_during_discovery:
            log_error("There was an error, removing " + ', '.join(("'" + d + "'" for d in cloned_during_discovery)))
            for d in cloned_during_discovery:
                shutil.rmtree(d)
        for d, (t, v) in original_version.items():
            if t == VersionType.REVISION:
                log_error("Reverting '{}' to version '{}'".format(d, v))
                VC.get_vc(d).update(d, v)
            elif t == VersionType.BRANCH:
                log_error("Reverting '{}' to branch '{}'".format(d, v))
                VC.get_vc(d).update_to_branch(d, v)
        raise se

    _log_discovery("Discovery finished")

    if register:
        # Register & finish loading discovered suites
        def _register_visit(s):
            _register_suite(s)
            for _suite_import in s.suite_imports:
                if _suite_import.name not in _suites:
                    _register_visit(discovered[_suite_import.name])
            if load:
                s._load()

        _register_visit(primary)

    _log_discovery("Registration/Loading finished")
    return primary

import mx_spotbugs
import mx_sigtest
import mx_gate
import mx_jackpot
import mx_compat
import mx_urlrewrites
import mx_benchmark
import mx_benchplot
import mx_downstream
import mx_subst

from mx_javamodules import JavaModuleDescriptor, make_java_module, get_java_module_info, lookup_package, get_transitive_closure, get_module_name

ERROR_TIMEOUT = 0x700000000 # not 32 bits

_mx_home = realpath(dirname(__file__))

try:
    # needed to work around https://bugs.python.org/issue1927
    import readline #pylint: disable=unused-import
except ImportError:
    pass


### ~~~~~~~~~~~~~ OS/Arch/Platform/System related

def download_file_exists(urls):
    """
    Returns true if one of the given urls denotes an existing resource.
    """
    for url in urls:
        try:
            _urlopen(url, timeout=0.5).close()
            return True
        except:
            pass
    return False


def download_file_with_sha1(name, path, urls, sha1, sha1path, resolve, mustExist, sources=False, canSymlink=True):
    """
    Downloads an entity from a URL in the list 'urls' (tried in order) to 'path',
    checking the sha1 digest of the result against 'sha1' (if not 'NOCHECK')
    Manages an internal cache of downloads and will link path to the cache entry unless 'canSymLink=False'
    in which case it copies the cache entry.
    """
    sha1Check = sha1 and sha1 != 'NOCHECK'
    canSymlink = canSymlink and not (is_windows() or is_cygwin())

    if len(urls) == 0 and not sha1Check:
        return path

    if not _check_file_with_sha1(path, sha1, sha1path, mustExist=resolve and mustExist):
        if len(urls) == 0:
            abort('SHA1 of {} ({}) does not match expected value ({})'.format(path, sha1OfFile(path), sha1))

        if is_cache_path(path):
            cachePath = path
        else:
            cachePath = _get_path_in_cache(name, sha1, urls, sources=sources)

        def _copy_or_symlink(source, link_name):
            ensure_dirname_exists(link_name)
            if canSymlink and 'symlink' in dir(os):
                logvv('Symlinking {} to {}'.format(link_name, source))
                if os.path.lexists(link_name):
                    os.unlink(link_name)
                try:
                    os.symlink(source, link_name)
                except OSError as e:
                    # When doing parallel building, the symlink can fail
                    # if another thread wins the race to create the symlink
                    if not os.path.lexists(link_name):
                        # It was some other error
                        raise Exception(link_name, e)
            else:
                # If we can't symlink, then atomically copy. Never move as that
                # can cause problems in the context of multiple processes/threads.
                with SafeFileCreation(link_name) as sfc:
                    logvv('Copying {} to {}'.format(source, link_name))
                    shutil.copy(source, sfc.tmpPath)

        cache_path_parent = dirname(cachePath)
        if is_cache_path(cache_path_parent):
            if exists(cache_path_parent) and not isdir(cache_path_parent):
                logv('Wiping bad cache file: {}'.format(cache_path_parent))
                # Some old version created bad files at this location, wipe it!
                try:
                    os.unlink(cache_path_parent)
                except OSError as e:
                    # we don't care about races, only about getting rid of this file
                    if exists(cache_path_parent) and not isdir(cache_path_parent):
                        raise e

        if not exists(cachePath):
            oldCachePath = _get_path_in_cache(name, sha1, urls, sources=sources, oldPath=True)
            if exists(oldCachePath):
                logv('Migrating cache file of {} from {} to {}'.format(name, oldCachePath, cachePath))
                _copy_or_symlink(oldCachePath, cachePath)
                _copy_or_symlink(oldCachePath + '.sha1', cachePath + '.sha1')

        if not exists(cachePath) or (sha1Check and sha1OfFile(cachePath) != sha1):
            if exists(cachePath):
                log('SHA1 of ' + cachePath + ' does not match expected value (' + sha1 + ') - found ' + sha1OfFile(cachePath) + ' - re-downloading')

            log('Downloading ' + ("sources " if sources else "") + name + ' from ' + str(urls))
            download(cachePath, urls)

        if path != cachePath:
            _copy_or_symlink(cachePath, path)

        if not _check_file_with_sha1(path, sha1, sha1path, newFile=True, logErrors=True):
            abort("No valid file for {} after download. Broken download? SHA1 not updated in suite.py file?".format(path))

    return path


def dir_contains_files_recursively(directory, file_pattern):
    for file_name in os.listdir(directory):
        file_path = join(directory, file_name)
        found = dir_contains_files_recursively(file_path, file_pattern) if isdir(file_path) \
            else re.match(file_pattern, file_name)
        if found:
            return True
    return False

def _cygpathU2W(p):
    """
    Translate a path from unix-style to windows-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or not is_cygwin():
        return p
    return _check_output_str(['cygpath', '-a', '-w', p]).strip()

def _cygpathW2U(p):
    """
    Translate a path from windows-style to unix-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or not is_cygwin():
        return p
    return _check_output_str(['cygpath', '-a', '-u', p]).strip()

def _separatedCygpathU2W(p):
    """
    Translate a group of paths, separated by a path separator.
    unix-style to windows-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or p == "" or not is_cygwin():
        return p
    return ';'.join(map(_cygpathU2W, p.split(os.pathsep)))

def _separatedCygpathW2U(p):
    """
    Translate a group of paths, separated by a path separator.
    windows-style to unix-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or p == "" or not is_cygwin():
        return p
    return os.pathsep.join(map(_cygpathW2U, p.split(';')))

def get_arch():
    machine = platform.uname()[4]
    if machine in ['aarch64']:
        return 'aarch64'
    if machine in ['amd64', 'AMD64', 'x86_64', 'i86pc']:
        return 'amd64'
    if machine in ['sun4v', 'sun4u', 'sparc64']:
        return 'sparcv9'
    if machine == 'i386' and is_darwin():
        try:
            # Support for Snow Leopard and earlier version of MacOSX
            if _check_output_str(['sysctl', '-n', 'hw.cpu64bit_capable']).strip() == '1':
                return 'amd64'
        except OSError:
            # sysctl is not available
            pass
    abort('unknown or unsupported architecture: os=' + get_os() + ', machine=' + machine)

mx_subst.results_substitutions.register_no_arg('arch', get_arch)

def vc_system(kind, abortOnError=True):
    for vc in _vc_systems:
        if vc.kind == kind:
            vc.check()
            return vc
    if abortOnError:
        abort('no VC system named ' + kind)
    else:
        return None

@suite_context_free
def sha1(args):
    """generate sha1 digest for given file"""
    parser = ArgumentParser(prog='sha1')
    parser.add_argument('--path', action='store', help='path to file', metavar='<path>', required=True)
    parser.add_argument('--plain', action='store_true', help='just the 40 chars', )
    args = parser.parse_args(args)
    value = sha1OfFile(args.path)
    if args.plain:
        sys.stdout.write(value)
    else:
        print('sha1 of ' + args.path + ': ' + value)


def sha1OfFile(path):
    with open(path, 'rb') as f:
        d = hashlib.sha1()
        while True:
            buf = f.read(4096)
            if not buf:
                break
            d.update(buf)
        return d.hexdigest()


def user_home():
    return _opts.user_home if hasattr(_opts, 'user_home') else os.path.expanduser('~')


def dot_mx_dir():
    return join(user_home(), '.mx')


def is_cache_path(path):
    return path.startswith(_cache_dir())

def relpath_or_absolute(path, start, prefix=""):
    """
    Finds a relative path and joins it to 'prefix', or otherwise tries to use 'path' as an absolute path.
    If 'path' is not an absolute path, an error is thrown.
    """
    try:
        return join(prefix, os.path.relpath(path, start))
    except ValueError:
        if not os.path.isabs(path):
            raise ValueError('can not find a relative path to dependency and path is not absolute: ' + path)
        return path

def cpu_count():
    cpus = multiprocessing.cpu_count()
    if _opts.cpu_count:
        return cpus if cpus <= _opts.cpu_count else _opts.cpu_count
    else:
        return cpus


def is_darwin():
    return sys.platform.startswith('darwin')


def is_linux():
    return sys.platform.startswith('linux')


def is_openbsd():
    return sys.platform.startswith('openbsd')


def is_sunos():
    return sys.platform.startswith('sunos')


def is_windows():
    return sys.platform.startswith('win32')


def is_cygwin():
    return sys.platform.startswith('cygwin')


def get_os():
    """
    Get a canonical form of sys.platform.
    """
    if is_darwin():
        return 'darwin'
    elif is_linux():
        return 'linux'
    elif is_openbsd():
        return 'openbsd'
    elif is_sunos():
        return 'solaris'
    elif is_windows():
        return 'windows'
    elif is_cygwin():
        return 'cygwin'
    else:
        abort('Unknown operating system ' + sys.platform)


def _is_process_alive(p):
    if isinstance(p, subprocess.Popen):
        return p.poll() is None
    assert isinstance(p, multiprocessing.Process), p
    return p.is_alive()


def _send_sigquit():
    for p, args in _currentSubprocesses:

        def _isJava():
            if args:
                name = args[0].split(os.sep)[-1]
                return name == "java"
            return False

        if p is not None and _is_process_alive(p) and _isJava():
            if is_windows():
                log("mx: implement me! want to send SIGQUIT to my child process")
            else:
                # only send SIGQUIT to the child not the process group
                logv('sending SIGQUIT to ' + str(p.pid))
                os.kill(p.pid, signal.SIGQUIT)
            time.sleep(0.1)


def abort(codeOrMessage, context=None, killsig=signal.SIGTERM):
    """
    Aborts the program with a SystemExit exception.
    If `codeOrMessage` is a plain integer, it specifies the system exit status;
    if it is None, the exit status is zero; if it has another type (such as a string),
    the object's value is printed and the exit status is 1.

    The `context` argument can provide extra context for an error message.
    If `context` is callable, it is called and the returned value is printed.
    If `context` defines a __abort_context__ method, the latter is called and
    its return value is printed. Otherwise str(context) is printed.
    """

    if _opts and hasattr(_opts, 'killwithsigquit') and _opts.killwithsigquit:
        logv('sending SIGQUIT to subprocesses on abort')
        _send_sigquit()

    for p, args in _currentSubprocesses:
        if _is_process_alive(p):
            if is_windows():
                p.terminate()
            else:
                _kill_process(p.pid, killsig)
            time.sleep(0.1)
        if _is_process_alive(p):
            try:
                if is_windows():
                    p.terminate()
                else:
                    _kill_process(p.pid, signal.SIGKILL)
            except BaseException as e:
                if _is_process_alive(p):
                    log_error('error while killing subprocess {0} "{1}": {2}'.format(p.pid, ' '.join(args), e))

    if _opts and hasattr(_opts, 'verbose') and _opts.verbose:
        import traceback
        traceback.print_stack()
    if context is not None:
        if callable(context):
            contextMsg = context()
        elif hasattr(context, '__abort_context__'):
            contextMsg = context.__abort_context__()
        else:
            contextMsg = str(context)
    else:
        contextMsg = ""

    if isinstance(codeOrMessage, int):
        # Log the context separately so that SystemExit
        # communicates the intended exit status
        error_message = contextMsg
        error_code = codeOrMessage
    elif contextMsg:
        error_message = contextMsg + ":\n" + codeOrMessage
        error_code = 1
    else:
        error_message = codeOrMessage
        error_code = 1
    log_error(error_message)
    raise SystemExit(error_code)


def abort_or_warn(message, should_abort, context=None):
    if should_abort:
        abort(message, context)
    else:
        warn(message, context)


def _suggest_http_proxy_error(e):
    """
    Displays a message related to http proxies that may explain the reason for the exception `e`.
    """
    proxyVars = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']
    proxyDefs = {k: _original_environ[k] for k in proxyVars if k in _original_environ.keys()}
    if not proxyDefs:
        warn('** If behind a firewall without direct internet access, use the http_proxy environment variable ' \
             '(e.g. "env http_proxy=proxy.company.com:80 mx ...") or download manually with a web browser.')
    else:
        defs = [i[0] + '=' + i[1] for i in proxyDefs.items()]
        warn(
            '** You have the following environment variable(s) set which may be the cause of the URL error:\n  ' + '\n  '.join(
                defs))


def _suggest_tlsv1_error(e):
    """
    Displays a message related to TLS errors that can occur when connecting to certain websites
    (e.g., github) on a version of Python that uses an older implementaiton of OpenSSL.
    """
    if 'tlsv1 alert protocol version' in str(e):
        warn('It seems that you have a version of python ({}) that uses an older version of OpenSSL. '.format(
            sys.executable) +
             'This should be fixed by installing the latest 2.7 release from https://www.python.org/downloads')


def getmtime(name):
    """
    Wrapper for builtin open function that handles long path names on Windows.
    """
    return os.path.getmtime(_safe_path(name))


def stat(name):
    """
    Wrapper for builtin open function that handles long path names on Windows.
    """
    return os.stat(_safe_path(name))


def lstat(name):
    """
    Wrapper for builtin open function that handles long path names on Windows.
    """
    return os.lstat(_safe_path(name))


def open(name, mode='r'):  # pylint: disable=redefined-builtin
    """
    Wrapper for builtin open function that handles long path names on Windows.
    """
    return builtins.open(_safe_path(name), mode=mode)


def copytree(src, dst, symlinks=False, ignore=None):
    shutil.copytree(_safe_path(src), _safe_path(dst), symlinks, ignore)


def rmtree(path, ignore_errors=False):
    path = _safe_path(path)
    if ignore_errors:
        def on_error(*args):
            pass
    elif is_windows():
        def on_error(func, _path, exc_info):
            os.chmod(_path, S_IWRITE)
            if isdir(_path):
                os.rmdir(_path)
            else:
                os.unlink(_path)
    else:
        def on_error(*args):
            raise  # pylint: disable=misplaced-bare-raise
    if isdir(path):
        shutil.rmtree(path, onerror=on_error)
    else:
        try:
            os.remove(path)
        except OSError:
            on_error(os.remove, path, sys.exc_info())


def clean(args, parser=None):
    """remove all class files, images, and executables

    Removes all files created by a build, including Java class files, executables, and
    generated images.
    """

    suppliedParser = parser is not None

    parser = parser if suppliedParser else ArgumentParser(prog='mx clean')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not clean native projects')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not clean Java projects')
    parser.add_argument('--dependencies', '--projects', action='store',
                        help='comma separated projects to clean (omit to clean all projects)')
    parser.add_argument('--no-dist', action='store_false', dest='dist', help='do not delete distributions')
    parser.add_argument('--all', action='store_true', help='clear all dependencies (not just default targets)')

    args = parser.parse_args(args)

    def _collect_clean_dependencies():
        if args.all:
            return dependencies(True)
        _, roots = defaultDependencies(True)
        res = []
        walk_deps(roots, visit=lambda d, e: res.append(d))
        return _dependencies_opt_limit_to_suites(res)

    if args.dependencies is not None:
        deps = [dependency(name) for name in args.dependencies.split(',')]
    else:
        deps = _collect_clean_dependencies()

    # TODO should we clean all the instantiations of a template?, how to enumerate all instantiations?
    for dep in deps:
        task = dep.getBuildTask(args)
        if task.cleanForbidden():
            continue
        task.logClean()
        task.clean()

        for configName in ['netbeans-config.zip', 'eclipse-config.zip']:
            config = TimeStampFile(join(dep.suite.get_mx_output_dir(), configName))
            if config.exists():
                os.unlink(config.path)

    if suppliedParser:
        return args


_tar_compressed_extensions = {'bz2', 'gz', 'lz', 'lzma', 'xz', 'Z'}
_known_zip_pre_extensions = {'src'}


def get_file_extension(path):
    root, ext = os.path.splitext(path)
    if len(ext) > 0:
        ext = ext[1:]  # remove leading .
    if ext in _tar_compressed_extensions and os.path.splitext(root)[1] == ".tar":
        return "tar." + ext
    if ext == 'zip':
        _, pre_ext = os.path.splitext(root)
        if len(pre_ext) > 0:
            pre_ext = pre_ext[1:]  # remove leading .
        if pre_ext in _known_zip_pre_extensions:
            return pre_ext + ".zip"
    if ext == 'map':
        _, pre_ext = os.path.splitext(root)
        if len(pre_ext) > 0:
            pre_ext = pre_ext[1:]  # remove leading .
            return pre_ext + ".map"
    return ext


def change_file_extension(path, new_extension):
    ext = get_file_extension(path)
    if not ext:
        return path + '.' + new_extension
    return path[:-len(ext)] + new_extension


def change_file_name(path, new_file_name):
    return join(dirname(path), new_file_name + '.' + get_file_extension(path))


def ensure_dirname_exists(path, mode=None):
    d = dirname(path)
    if d != '':
        ensure_dir_exists(d, mode)


def ensure_dir_exists(path, mode=None):
    """
    Ensures all directories on 'path' exists, creating them first if necessary with os.makedirs().
    """
    if not isdir(path):
        try:
            if mode:
                os.makedirs(path, mode=mode)
            else:
                os.makedirs(path)
        except OSError as e:
            if e.errno == errno.EEXIST and isdir(path):
                # be happy if another thread already created the path
                pass
            else:
                raise e
    return path

def show_envs(args):
    """print environment variables and their values

    By default only variables starting with "MX" are shown.
    The --all option forces all variables to be printed"""
    parser = ArgumentParser(prog='mx envs')
    parser.add_argument('--all', action='store_true', help='show all variables, not just those starting with "MX"')
    args = parser.parse_args(args)

    for key, value in os.environ.items():
        if args.all or key.startswith('MX'):
            print('{0}: {1}'.format(key, value))


def _attempt_download(url, path, jarEntryName=None):
    """
    Attempts to download content from `url` and save it to `path`.
    If `jarEntryName` is not None, then the downloaded content is
    expected to be a zip/jar file and the entry of the corresponding
    name is extracted and written to `path`.

    :return: True if the download succeeded, "retry" if it failed but might succeed
            if retried, False otherwise
    """

    progress = not _opts.no_download_progress and sys.stdout.isatty()
    conn = None
    try:
        # Use a temp file while downloading to avoid multiple threads overwriting the same file
        with SafeFileCreation(path) as sfc:
            tmp = sfc.tmpPath

            # 10 second timeout to establish connection
            url = url.replace('\\', '/')
            conn = _urlopen(url, timeout=10)

            # Not all servers support the "Content-Length" header
            lengthHeader = conn.headers.get('Content-Length')
            length = int(lengthHeader.strip()) if lengthHeader else -1

            bytesRead = 0
            chunkSize = 8192

            with open(tmp, 'wb') as fp:
                chunk = conn.read(chunkSize)
                while chunk:
                    bytesRead += len(chunk)
                    fp.write(chunk)
                    if length == -1:
                        if progress:
                            sys.stdout.write('\r {} bytes'.format(bytesRead))
                    else:
                        if progress:
                            sys.stdout.write('\r {} bytes ({}%)'.format(bytesRead, bytesRead * 100 / length))
                        if bytesRead == length:
                            break
                    chunk = conn.read(chunkSize)

            if progress:
                sys.stdout.write('\n')

            if length not in (-1, bytesRead):
                log_error('Download of {} truncated: read {} of {} bytes.'.format(url, bytesRead, length))
                return "retry"

            if jarEntryName:
                with zipfile.ZipFile(tmp, 'r') as zf:
                    jarEntry = zf.read(jarEntryName)
                with open(tmp, 'wb') as fp:
                    fp.write(jarEntry)

            return True

    except (IOError, socket.timeout, _urllib_error.HTTPError) as e:
        # In case of an exception the temp file is removed automatically, so no cleanup is necessary
        log_error("Error reading from " + url + ": " + str(e))
        _suggest_http_proxy_error(e)
        _suggest_tlsv1_error(e)
        if isinstance(e, _urllib_error.HTTPError) and e.code == 500:
            return "retry"
    finally:
        if conn:
            conn.close()
    return False

def download(path, urls, verbose=False, abortOnError=True, verifyOnly=False):
    """
    Attempts to downloads content for each URL in a list, stopping after the first successful download.
    If the content cannot be retrieved from any URL, the program is aborted, unless abortOnError=False.
    The downloaded content is written to the file indicated by `path`.
    """
    if not verifyOnly:
        ensure_dirname_exists(path)
        assert not path.endswith(os.sep)

    # https://docs.oracle.com/javase/7/docs/api/java/net/JarURLConnection.html
    jarURLPattern = re.compile('jar:(.*)!/(.*)')
    verify_errors = {}
    for url in urls:
        if not verifyOnly or verbose:
            log('Downloading ' + url + ' to ' + path)
        m = jarURLPattern.match(url)
        jarEntryName = None
        if m:
            url = m.group(1)
            jarEntryName = m.group(2)

        if verifyOnly:
            try:
                conn = _urlopen(url, timeout=10)
                conn.close()
                return True
            except (IOError, socket.timeout) as e:
                _suggest_tlsv1_error(e)
                verify_errors[url] = e
            continue

        for i in range(4):
            if i != 0:
                time.sleep(1)
                warn('Retry {} to download from {}'.format(i, url))
            res = _attempt_download(url, path, jarEntryName)
            if res is True:
                return True
            if res is False:
                break

    if abortOnError:
        msg = 'Could not download to ' + path + ' from any of the following URLs: ' + ', '.join(urls)
        if verifyOnly:
            for url, e in verify_errors.items():
                msg += '\n  ' + url + ': ' + str(e)
        abort(msg)
    else:
        return False

def update_file(path, content, showDiff=False):
    """
    Updates a file with some given content if the content differs from what's in
    the file already. The return value indicates if the file was updated.
    """
    existed = exists(path)
    try:
        old = None
        if existed:
            with open(path, 'r') as f:
                old = f.read()

        if old == content:
            return False

        if existed and _opts.backup_modified:
            shutil.move(path, path + '.orig')

        with open(path, 'w') as f:
            f.write(content)

        if existed:
            log('modified ' + path)
            if _opts.backup_modified:
                log('backup ' + path + '.orig')
            if showDiff:
                log('diff: ' + path)
                log(''.join(difflib.unified_diff(old.splitlines(1), content.splitlines(1))))
        else:
            log('created ' + path)
        return True
    except IOError as e:
        abort('Error while writing to ' + path + ': ' + str(e))


try: zipfile.ZipFile.__enter__
except:
    zipfile.ZipFile.__enter__ = lambda self: self
    zipfile.ZipFile.__exit__ = lambda self, t, value, traceback: self.close()

_projects = dict()
_libs = dict()
"""
:type: dict[str, ResourceLibrary|Library]
"""
_jreLibs = dict()
"""
:type: dict[str, JreLibrary]
"""
_jdkLibs = dict()
"""
:type: dict[str, JdkLibrary]
"""
_dists = dict()
_distTemplates = dict()
_licenses = dict()
_repositories = dict()
_mavenRepoBaseURLs = [
    "https://repo1.maven.org/maven2/",
    "https://search.maven.org/remotecontent?filepath="
]

_suites = dict()
"""
Map of the environment variables loaded by parsing the suites.
"""
_loadedEnv = dict()

_jdkFactories = {}

_annotationProcessors = None
_mx_suite = None
_mx_tests_suite = None
_suitemodel = None
_opts = Namespace()
_extra_java_homes = []
_default_java_home = None
_check_global_structures = True  # can be set False to allow suites with duplicate definitions to load without aborting
_vc_systems = []
_mvn = None
_binary_suites = None  # source suites only if None, [] means all binary, otherwise specific list
_urlrewrites = []  # list of URLRewrite objects
_original_environ = dict(os.environ)
_original_directory = os.getcwd()
_jdkProvidedSuites = set()

# List of functions to run after options have been parsed
_opts_parsed_deferrables = []


def nyi(name, obj):
    abort('{} is not implemented for {}'.format(name, obj.__class__.__name__))
    raise NotImplementedError()

### Dependencies

"""
Map from the name of a removed dependency to the reason it was removed.
A reason may be the name of another removed dependency, forming a causality chain.
"""
_removedDeps = {}

def _check_dependency_cycles():
    """
    Checks for cycles in the dependency graph.
    """
    path = []
    def _visitEdge(src, dst, edge):
        if dst in path:
            abort('dependency cycle detected: ' + ' -> '.join([d.name for d in path] + [dst.name]), context=dst)
    def _preVisit(dep, edge):
        path.append(dep)
        return True
    def _visit(dep, edge):
        last = path.pop(-1)
        assert last is dep
    walk_deps(ignoredEdges=[DEP_EXCLUDED], preVisit=_preVisit, visitEdge=_visitEdge, visit=_visit)


def _remove_unsatisfied_deps():
    """
    Remove projects and libraries that (recursively) depend on an optional library
    whose artifact does not exist or on a JRE library that is not present in the
    JDK for a project. Also remove projects whose Java compliance requirement
    cannot be satisfied by the configured JDKs. Removed projects and libraries are
    also removed from distributions in which they are listed as dependencies.
    Returns a map from the name of a removed dependency to the reason it was removed.
    A reason may be the name of another removed dependency.
    """
    removedDeps = OrderedDict()

    def visit(dep, edge):
        if dep.isLibrary():
            if dep.optional:
                if not dep.is_available():
                    note_removal(dep, 'optional library {0} was removed as it is not available'.format(dep))
            for depDep in list(dep.deps):
                if depDep in removedDeps:
                    note_removal(dep, 'removed {} because {} was removed'.format(dep, depDep))
        elif dep.isJavaProject():
            # TODO this lookup should be the same as the one used in build
            depJdk = get_jdk(dep.javaCompliance, cancel='some projects will be removed which may result in errors', purpose="building projects with compliance " + repr(dep.javaCompliance), tag=DEFAULT_JDK_TAG)
            if depJdk is None:
                note_removal(dep, 'project {0} was removed as JDK {0.javaCompliance} is not available'.format(dep))
            elif hasattr(dep, "javaVersionExclusion") and getattr(dep, "javaVersionExclusion") == depJdk.javaCompliance:
                note_removal(dep, 'project {0} was removed due to its "javaVersionExclusion" attribute'.format(dep))
            else:
                for depDep in list(dep.deps):
                    if depDep in removedDeps:
                        note_removal(dep, 'removed {} because {} was removed'.format(dep, depDep))
                    elif depDep.isJreLibrary() or depDep.isJdkLibrary():
                        lib = depDep
                        if not lib.is_provided_by(depJdk):
                            if lib.optional:
                                note_removal(dep, 'project {} was removed as dependency {} is missing'.format(dep, lib))
                            else:
                                abort('{} library {} required by {} not provided by {}'.format('JDK' if lib.isJdkLibrary() else 'JRE', lib, dep, depJdk), context=dep)
        elif dep.isJARDistribution() and not dep.suite.isBinarySuite():
            prune(dep, discard=lambda d: not any(dd.isProject()
                                                 or (dd.isBaseLibrary()
                                                     and not dd.isJdkLibrary()
                                                     and not dd.isJreLibrary()
                                                     and dd not in d.excludedLibs)
                                                 for dd in d.deps))
        elif dep.isTARDistribution():
            prune(dep)

        if hasattr(dep, 'ignore'):
            reasonAttr = getattr(dep, 'ignore')
            if isinstance(reasonAttr, bool):
                if reasonAttr:
                    abort('"ignore" attribute must be False/"false" or a non-empty string providing the reason the dependency is ignored', context=dep)
            else:
                assert isinstance(reasonAttr, str)
                strippedReason = reasonAttr.strip()
                if len(strippedReason) != 0:
                    if not strippedReason == "false":
                        note_removal(dep, '{} removed: {}'.format(dep, strippedReason))
                else:
                    abort('"ignore" attribute must be False/"false" or a non-empty string providing the reason the dependency is ignored', context=dep)
        if hasattr(dep, 'buildDependencies'):
            for buildDep in list(dep.buildDependencies):
                if buildDep in removedDeps:
                    note_removal(dep, 'removed {} because {} was removed'.format(dep, buildDep))

    def prune(dist, discard=lambda d: not (d.deps or d.buildDependencies)):
        assert dist.isDistribution()
        if dist.deps or dist.buildDependencies:
            distRemovedDeps = []
            for distDep in list(dist.deps) + list(dist.buildDependencies):
                if distDep in removedDeps:
                    logv('[{} was removed from distribution {}]'.format(distDep, dist))
                    dist.removeDependency(distDep)
                    distRemovedDeps.append(distDep)

            if discard(dist):
                note_removal(dist, 'distribution {} was removed as all its dependencies were removed'.format(dist),
                             details=[e.name for e in distRemovedDeps])

    def note_removal(dep, reason, details=None):
        logv('[' + reason + ']')
        removedDeps[dep] = reason if details is None else (reason, details)

    walk_deps(visit=visit, ignoredEdges=[DEP_EXCLUDED])

    res = OrderedDict()
    for dep, reason in removedDeps.items():
        if not isinstance(reason, str):
            assert isinstance(reason, tuple)
        res[dep.name] = reason
        dep.getSuiteRegistry().remove(dep)
        dep.getGlobalRegistry().pop(dep.name)
    return res

DEP_STANDARD = "standard dependency"
DEP_BUILD = "a build dependency"
DEP_ANNOTATION_PROCESSOR = "annotation processor dependency"
DEP_EXCLUDED = "library excluded from a distribution"

#: Set of known dependency edge kinds
DEP_KINDS = frozenset([DEP_STANDARD, DEP_BUILD, DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED])

def _is_edge_ignored(edge, ignoredEdges):
    return ignoredEdges and edge in ignoredEdges

DEBUG_WALK_DEPS = False
DEBUG_WALK_DEPS_LINE = 1
def _debug_walk_deps_helper(dep, edge, ignoredEdges):
    assert edge not in ignoredEdges
    global DEBUG_WALK_DEPS_LINE
    if DEBUG_WALK_DEPS:
        if edge:
            print('{}:walk_deps:{}{}    # {}'.format(DEBUG_WALK_DEPS_LINE, '  ' * edge.path_len(), dep, edge.kind))
        else:
            print('{}:walk_deps:{}'.format(DEBUG_WALK_DEPS_LINE, dep))
        DEBUG_WALK_DEPS_LINE += 1


class DepEdge:
    """
    Represents an edge traversed while visiting a spanning tree of the dependency graph.
    """
    def __init__(self, src, kind, prev):
        """
        :param src: the source of this dependency edge
        :param kind: one of the values in `DEP_KINDS`
        :param prev: the dependency edge traversed to reach `src` or None if `src` is a root
        """
        assert kind in DEP_KINDS
        self.src = src
        self.kind = kind
        self.prev = prev

    def __str__(self):
        return '{}@{}'.format(self.src, self.kind)

    def path(self):
        if self.prev:
            return self.prev.path() + [self.src]
        return [self.src]

    def path_len(self):
        return 1 + self.prev.path_len() if self.prev else 0


# for backwards compatibility
def _replaceResultsVar(m):
    return mx_subst.results_substitutions.substitute(m.group(0))

# for backwards compatibility
def _replacePathVar(m):
    return mx_subst.path_substitutions.substitute(m.group(0))

def _get_dependency_path(dname):
    d = dependency(dname)
    path = None
    if d.isJARDistribution() and hasattr(d, "path"):
        path = d.path
    elif d.isTARDistribution() and hasattr(d, "output"):
        path = d.output
    elif d.isLibrary() or d.isResourceLibrary():
        path = d.get_path(resolve=True)
    elif d.isProject():
        path = d.dir
    if path:
        return join(d.suite.dir, path)
    else:
        abort('dependency ' + dname + ' has no path')

mx_subst.path_substitutions.register_with_arg('path', _get_dependency_path)


class ClasspathDependency(Dependency):
    """
    A dependency that can be put on the classpath of a Java commandline.
    """
    __metaclass__ = ABCMeta

    def __init__(self, **kwArgs): # pylint: disable=super-init-not-called
        pass

    def classpath_repr(self, resolve=True):
        """
        Gets this dependency as an element on a class path.

        If 'resolve' is True, then this method aborts if the file or directory
        denoted by the class path element does not exist.
        :rtype : str
        """
        nyi('classpath_repr', self)

    def isJar(self):
        cp_repr = self.classpath_repr() #pylint: disable=assignment-from-no-return
        if cp_repr:
            return cp_repr.endswith('.jar') or cp_repr.endswith('.JAR') or '.jar_' in cp_repr
        return True

    def getJavaProperties(self, replaceVar=mx_subst.path_substitutions):
        """
        A dictionary of custom Java properties that should be added to the commandline
        """
        ret = {}
        if hasattr(self, "javaProperties"):
            for key, value in self.javaProperties.items():
                ret[key] = replaceVar.substitute(value, dependency=self)
        return ret


### JNI

def _get_jni_gen(pname):
    p = project(pname)
    if p.jni_gen_dir() is None:
        abort("Project {0} does not produce JNI headers, it can not be used in <jnigen:{0}> substitution.".format(pname))
    return join(p.suite.dir, p.jni_gen_dir())

mx_subst.path_substitutions.register_with_arg('jnigen', _get_jni_gen)

### ~~~~~~~~~~~~~ Build

class BuildTask(object):
    """
    A build task is used to build a dependency.
    :type deps: list[BuildTask]
    """
    __metaclass__ = ABCMeta

    def __init__(self, subject, args, parallelism):
        """
        :param Dependency subject: the dependency built by this task
        :param list[str] args: arguments to the build comment
        :param int parallelism: how many CPUs are used when running this task
        """
        self.parallelism = parallelism
        self.subject = subject
        self.deps = []
        self.built = False
        self.args = args
        self.proc = None
        self._saved_deps_path = join(subject.suite.get_mx_output_dir(), 'savedDeps', type(subject).__name__,
                                     subject._extra_artifact_discriminant(), subject.name)

    def __str__(self):
        nyi('__str__', self)

    def __repr__(self):
        return str(self)

    def initSharedMemoryState(self):
        self._builtBox = multiprocessing.Value('b', 1 if self.built else 0)

    def pushSharedMemoryState(self):
        self._builtBox.value = 1 if self.built else 0

    def pullSharedMemoryState(self):
        self.built = bool(self._builtBox.value)

    def cleanSharedMemoryState(self):
        self._builtBox = None

    @property
    def _current_deps(self):
        return [d.subject.name for d in self.deps]

    def _persist_deps(self):
        """
        Saves the dependencies for this task's subject to a file.
        """
        if self._current_deps:
            with SafeFileCreation(self._saved_deps_path) as sfc:
                with open(sfc.tmpPath, 'w') as f:
                    for d in self._current_deps:
                        print(d, file=f)
        elif exists(self._saved_deps_path):
            os.remove(self._saved_deps_path)

    def _deps_changed(self):
        """
        Returns True if there are saved dependencies for this task's subject and
        they have changed since the last time it was built.
        """
        if exists(self._saved_deps_path):
            with open(self._saved_deps_path) as f:
                if f.read().splitlines() != self._current_deps:
                    return True
        return False

    def execute(self):
        """
        Execute the build task.
        """
        if self.buildForbidden():
            self.logSkip()
            return
        buildNeeded = False
        if self.args.clean and not self.cleanForbidden():
            self.logClean()
            self.clean()
            buildNeeded = True
            reason = 'clean'
        if not buildNeeded:
            updated = [dep for dep in self.deps if dep.built]
            if any(updated):
                buildNeeded = True
                if not _opts.verbose:
                    reason = 'dependency {} updated'.format(updated[0].subject)
                else:
                    reason = 'dependencies updated: ' + ', '.join([u.subject.name for u in updated])
        if not buildNeeded and self._deps_changed():
            buildNeeded = True
            reason = 'dependencies were added, removed or re-ordered'
        if not buildNeeded:
            newestInput = None
            newestInputDep = None
            for dep in self.deps:
                depNewestOutput = dep.newestOutput()
                if depNewestOutput and (not newestInput or depNewestOutput.isNewerThan(newestInput)):
                    newestInput = depNewestOutput
                    newestInputDep = dep
            if newestInputDep:
                logvv('Newest dependency for {}: {} ({})'.format(self.subject.name, newestInputDep.subject.name,
                                                                 newestInput))

            if get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') is None:
                shallow_dependency_checks = self.args.shallow_dependency_checks is True
            else:
                shallow_dependency_checks = get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') == 'true'
                if self.args.shallow_dependency_checks is not None and shallow_dependency_checks is True:
                    warn('Explicit -s argument to build command is overridden by MX_BUILD_SHALLOW_DEPENDENCY_CHECKS')

            if newestInput and shallow_dependency_checks and not self.subject.isNativeProject():
                newestInput = None
            if __name__ != self.__module__ and not self.subject.suite.getMxCompatibility().newestInputIsTimeStampFile():
                newestInput = newestInput.timestamp if newestInput else float(0)
            buildNeeded, reason = self.needsBuild(newestInput)
        if buildNeeded:
            if not self.args.clean and not self.cleanForbidden():
                self.clean(forBuild=True)
            self.logBuild(reason)
            self.build()
            self._persist_deps()
            self.built = True
            logv('Finished {}'.format(self))
        else:
            self.logSkip(reason)

    def logBuild(self, reason=None):
        if reason:
            log('{}... [{}]'.format(self, reason))
        else:
            log('{}...'.format(self))

    def logClean(self):
        log('Cleaning {}...'.format(self.subject.name))

    def logSkip(self, reason=None):
        if reason:
            logv('[{} - skipping {}]'.format(reason, self.subject.name))
        else:
            logv('[skipping {}]'.format(self.subject.name))

    def needsBuild(self, newestInput):
        """
        Returns True if the current artifacts of this task are out dated.
        The 'newestInput' argument is either None or a TimeStampFile
        denoting the artifact of a dependency with the most recent modification time.
        Apart from 'newestInput', this method does not inspect this task's dependencies.
        """
        if self.args.force:
            return (True, 'forced build')
        return (False, 'unimplemented')

    # @abstractmethod should be abstract but subclasses in some suites miss this method
    def newestOutput(self):
        """
        Gets a TimeStampFile representing the build output file for this task
        with the newest modification time or None if no build output file exists.
        """
        nyi('newestOutput', self)

    def buildForbidden(self):
        if not self.args.only:
            return False
        projectNames = self.args.only.split(',')
        return self.subject.name not in projectNames

    def cleanForbidden(self):
        return False

    def prepare(self, daemons):
        """
        Perform any task initialization that must be done in the main process.
        This will be called just before the task is launched.
        The 'daemons' argument is a dictionary for storing any persistent state
        that might be shared between tasks.
        """

    @abstractmethod
    def build(self):
        """
        Build the artifacts.
        """
        nyi('build', self)

    @abstractmethod
    def clean(self, forBuild=False):
        """
        Clean the build artifacts.
        """
        nyi('clean', self)


### ~~~~~~~~~~~~~ Distribution, Archive, Dependency

class DistributionTemplate(SuiteConstituent):
    def __init__(self, suite, name, attrs, parameters):
        SuiteConstituent.__init__(self, suite, name)
        self.attrs = attrs
        self.parameters = parameters


class Distribution(Dependency):
    __metaclass__ = ABCMeta
    """
    A distribution is a file containing the output of one or more dependencies.
    It is a `Dependency` because a `Project` or another `Distribution` may express a dependency on it.

    :param Suite suite: the suite in which the distribution is defined
    :param str name: the name of the distribution which must be unique across all suites
    :param list deps: the dependencies of the distribution. How these dependencies are consumed
           is defined by the `Distribution` subclasses.
    :param list excludedLibs: libraries whose contents should be excluded from this distribution's built artifact
    :param bool platformDependent: specifies if the built artifact is platform dependent
    :param str theLicense: license applicable when redistributing the built artifact of the distribution
    """
    def __init__(self, suite, name, deps, excludedLibs, platformDependent, theLicense, testDistribution=False, platforms=None, **kwArgs):
        Dependency.__init__(self, suite, name, theLicense, **kwArgs)
        self.deps = deps
        self.update_listeners = set()
        self.excludedLibs = excludedLibs
        self.platformDependent = platformDependent
        self.platforms = platforms or [None]
        self.buildDependencies = []
        if testDistribution is None:
            self.testDistribution = name.endswith('_TEST') or name.endswith('_TESTS')
        else:
            self.testDistribution = testDistribution

    def is_test_distribution(self):
        return self.testDistribution

    def isPlatformDependent(self):
        return self.platformDependent

    def add_update_listener(self, listener):
        self.update_listeners.add(listener)

    def notify_updated(self):
        for l in self.update_listeners:
            l(self)

    def removeDependency(self, dep):
        if dep in self.deps:
            self.deps.remove(dep)
        if dep in self.buildDependencies:
            self.buildDependencies.remove(dep)

    def resolveDeps(self):
        self._resolveDepsHelper(self.deps, fatalIfMissing=not isinstance(self.suite, BinarySuite))
        if self.suite.getMxCompatibility().automatic_overlay_distribution_deps():
            for d in self.deps:
                if d.isJavaProject() and d._overlays:
                    for o in d._overlays:
                        if o in self.deps:
                            abort('Distribution must not explicitly specify a dependency on {} as it is derived automatically.'.format(o), context=self)
                        self.deps.append(o)
        self._resolveDepsHelper(self.buildDependencies, fatalIfMissing=not isinstance(self.suite, BinarySuite))
        self._resolveDepsHelper(self.excludedLibs)
        self._resolveDepsHelper(getattr(self, 'moduledeps', None))
        overlaps = getattr(self, 'overlaps', [])
        if not isinstance(overlaps, list):
            abort('Attribute "overlaps" must be a list', self)
        original_overlaps = list(overlaps)
        self._resolveDepsHelper(overlaps)
        self.resolved_overlaps = overlaps
        self.overlaps = original_overlaps
        for l in self.excludedLibs:
            if not l.isBaseLibrary():
                abort('"exclude" attribute can only contain libraries: ' + l.name, context=self)
        licenseId = self.theLicense if self.theLicense else self.suite.defaultLicense
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)

    def _walk_deps_visit_edges(self, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        deps = [(DEP_STANDARD, self.deps), (DEP_EXCLUDED, self.excludedLibs), (DEP_BUILD, self.buildDependencies)]
        self._walk_deps_visit_edges_helper(deps, visited, in_edge, preVisit=preVisit, visit=visit, ignoredEdges=ignoredEdges, visitEdge=visitEdge)

    def make_archive(self):
        nyi('make_archive', self)

    def archived_deps(self):
        """
        Gets the projects and libraries whose artifacts are the contents of the archive
        created by `make_archive`.

        Direct distribution dependencies are considered as _distDependencies_.
        Anything contained in the _distDependencies_ will not be included in the result.
        Libraries listed in `excludedLibs` will also be excluded.
        Otherwise, the result will contain everything this distribution depends on (including
        indirect distribution dependencies and libraries).
        """
        if not hasattr(self, '.archived_deps'):
            excluded = set(self.excludedLibs)
            def _visitDists(dep, edges):
                if dep is not self:
                    excluded.add(dep)
                    if dep.isDistribution():
                        for o in dep.overlapped_distributions():
                            excluded.add(o)
                    excluded.update(dep.archived_deps())
            self.walk_deps(visit=_visitDists, preVisit=lambda dst, edge: dst.isDistribution())
            deps = []
            def _visit(dep, edges):
                if dep is not self:
                    deps.append(dep)
            def _preVisit(dst, edge):
                if edge and edge.src.isNativeProject():
                    # A native project dependency only denotes a build order dependency
                    return False
                return dst not in excluded and not dst.isJreLibrary() and not dst.isJdkLibrary()
            self.walk_deps(visit=_visit, preVisit=_preVisit)
            if self.suite.getMxCompatibility().automatic_overlay_distribution_deps():
                for d in deps:
                    if d.isJavaProject() and d._overlays and d not in self.deps:
                        abort('Distribution must explicitly specify a dependency on {} as it has overlays. {}'.format(d, self), context=self)
            setattr(self, '.archived_deps', deps)
        return getattr(self, '.archived_deps')

    @abstractmethod
    def exists(self):
        nyi('exists', self)

    @abstractmethod
    def remoteExtension(self):
        nyi('remoteExtension', self)

    @abstractmethod
    def localExtension(self):
        nyi('localExtension', self)

    def _default_path(self):
        return join(self.suite.get_output_root(platformDependent=self.platformDependent), 'dists',
                    self._extra_artifact_discriminant(), self.default_filename())

    def default_filename(self):
        return _map_to_maven_dist_name(self.name) + '.' + self.localExtension()

    @classmethod
    def platformName(cls):
        return '{os}_{arch}'.format(os=get_os(), arch=get_arch())

    """
    Provide remoteName of distribution.

    :param str platform: If the distribution is platform dependent and platform is provided
           it will be used instead of the usual platform suffix (provided by platformName()).
    """
    def remoteName(self, platform=None):
        if self.platformDependent:
            if not platform:
                platform = self.platformName()
            return '{name}_{platform}'.format(name=self.name, platform=platform)
        return self.name

    def postPull(self, f):
        pass

    def prePush(self, f):
        return f

    def needsUpdate(self, newestInput):
        """
        Determines if this distribution needs updating taking into account the
        'newestInput' TimeStampFile if 'newestInput' is not None. Returns the
        reason this distribution needs updating or None if it doesn't need updating.
        """
        nyi('needsUpdate', self)

    """
    Provide maven artifactId string for distribution.

    :param str platform: If the distribution is platform dependent and platform is provided
           it will be used instead of the usual platform suffix (provided by platformName()).
    """
    def maven_artifact_id(self, platform=None):
        if hasattr(self, 'maven') and isinstance(self.maven, dict):
            artifact_id = self.maven.get('artifactId', None)
            if artifact_id:
                return artifact_id
        return _map_to_maven_dist_name(self.remoteName(platform=platform))

    """
    Provide maven groupId string for distribution.
    """
    def maven_group_id(self):
        if hasattr(self, 'maven') and isinstance(self.maven, dict):
            group_id = self.maven.get('groupId', None)
            if group_id:
                return group_id
        return _mavenGroupId(self.suite)

    def overlapped_distribution_names(self):
        return self.overlaps

    def overlapped_distributions(self):
        return self.resolved_overlaps

    def post_init(self):
        pass


class JARDistribution(Distribution, ClasspathDependency):
    """
    A distribution represents a jar file built from the class files and resources defined by a set of
    `JavaProject`s and Java libraries plus an optional zip containing the Java source files
    corresponding to the class files.

    :param Suite suite: the suite in which the distribution is defined
    :param str name: the name of the distribution which must be unique across all suites
    :param list stripConfigFileNames: names of stripping configurations that are located in `<mx_dir>/proguard/` and suffixed with `.proguard`
    :param list stripMappingFileNames: names of stripping maps that are located in `<mx_dir>/proguard/` and suffixed with `.map`
    :param str | None subDir: a path relative to `suite.dir` in which the IDE project configuration for this distribution is generated
    :param str path: the path of the jar file created for this distribution. If this is not an absolute path,
           it is interpreted to be relative to `suite.dir`.
    :param str | None sourcesPath: the path of the zip file created for the source files corresponding to the class files of this distribution.
           If this is not an absolute path, it is interpreted to be relative to `suite.dir`.
    :param list deps: the `JavaProject` and `Library` dependencies that are the root sources for this distribution's jar
    :param str | None mainClass: the class name representing application entry point for this distribution's executable jar. This
           value (if not None) is written to the ``Main-Class`` header in the jar's manifest.
    :param list excludedLibs: libraries whose contents should be excluded from this distribution's jar
    :param list distDependencies: the `JARDistribution` dependencies that must be on the class path when this distribution
           is on the class path (at compile or run time)
    :param str | None javaCompliance:
    :param bool platformDependent: specifies if the built artifact is platform dependent
    :param str | None theLicense: license applicable when redistributing the built artifact of the distribution
    :param str javadocType: specifies if the javadoc generated for this distribution should include implementation documentation
           or only API documentation. Accepted values are "implementation" and "API".
    :param bool allowsJavadocWarnings: specifies whether warnings are fatal when javadoc is generated
    :param bool maven:
    :param dict[str, str] | None manifestEntries: Entries for the `META-INF/MANIFEST.MF` file.
    """
    def __init__(self, suite, name, subDir, path, sourcesPath, deps, mainClass, excludedLibs, distDependencies, javaCompliance, platformDependent, theLicense,
                 javadocType="implementation", allowsJavadocWarnings=False, maven=True, stripConfigFileNames=None,
                 stripMappingFileNames=None, manifestEntries=None, **kwArgs):
        assert manifestEntries is None or isinstance(manifestEntries, dict)
        Distribution.__init__(self, suite, name, deps + distDependencies, excludedLibs, platformDependent, theLicense, **kwArgs)
        ClasspathDependency.__init__(self, **kwArgs)
        self.subDir = subDir
        if path:
            path = mx_subst.path_substitutions.substitute(path)
            self._path = _make_absolute(path.replace('/', os.sep), self.suite.dir)
        else:
            self._path = None
        if sourcesPath == '<none>':
            # `<none>` is used in the `suite.py` is used to specify that there should be no source zip.
            self._sources_path = None
        elif sourcesPath:
            sources_path = mx_subst.path_substitutions.substitute(sourcesPath)
            self._sources_path = _make_absolute(sources_path.replace('/', os.sep), self.suite.dir)
        else:
            self._sources_path = '<uninitialized>'

        self.archiveparticipants = []
        self.mainClass = mainClass
        self.javaCompliance = JavaCompliance(javaCompliance) if javaCompliance else None
        self.definedAnnotationProcessors = []
        self.javadocType = javadocType
        self.allowsJavadocWarnings = allowsJavadocWarnings
        self.maven = maven
        self.manifestEntries = dict([]) if manifestEntries is None else manifestEntries
        if stripConfigFileNames:
            self.stripConfig = [join(suite.mxDir, 'proguard', stripConfigFileName + '.proguard') for stripConfigFileName in stripConfigFileNames]
        else:
            self.stripConfig = None
        if stripMappingFileNames:
            self.stripMapping = [join(suite.mxDir, 'proguard', stripMappingFileName + '.map') for stripMappingFileName in stripMappingFileNames]
        else:
            self.stripMapping = []
        if self.is_stripped():
            # Make this a build dependency to avoid concurrency issues that can arise
            # when the library is lazily resolved by build tasks (which can be running
            # concurrently).
            self.buildDependencies.append("mx:PROGUARD_6_0_3")

    def post_init(self):
        # paths are initialized late to be able to figure out the max jdk
        if self._path is None:
            self._path = _make_absolute(self._default_path(), self.suite.dir)

        if self._sources_path == '<uninitialized>':
            # self._sources_path== '<uninitialized>' denotes that no sourcesPath was specified in `suite.py` and we should generate one.
            self._sources_path = _make_absolute(self._default_source_path(), self.suite.dir)

        assert self.path.endswith(self.localExtension())

    def default_source_filename(self):
        return _map_to_maven_dist_name(self.name) + '.src.zip'

    def _default_source_path(self):
        return join(dirname(self._default_path()), self.default_source_filename())

    def _extra_artifact_discriminant(self):
        if self.suite.isBinarySuite() or not self.suite.getMxCompatibility().jarsUseJDKDiscriminant():
            return ''
        compliance = self._compliance_for_build()
        if compliance:
            return 'jdk{}'.format(compliance)
        return ''

    def _compliance_for_build(self):
        # This JAR will contain class files up to maxJavaCompliance
        compliance = self.maxJavaCompliance()
        if compliance is not None and compliance < '9' and get_module_name(self):
            # if it is modular, bump compliance to 9+ to get a module-info file
            jdk9 = get_jdk('9+', cancel='No module-info will be generated for modular JAR distributions')
            if jdk9:
                compliance = max(compliance, jdk9.javaCompliance)
        return compliance

    @property
    def path(self):
        if self.is_stripped():
            return self._stripped_path()
        else:
            return self.original_path()

    def _stripped_path(self):
        assert self._path is not None, self.name
        return join(ensure_dir_exists(join(dirname(self._path), 'stripped')), basename(self._path))

    def original_path(self):
        assert self._path is not None, self.name
        return self._path

    @property
    def sourcesPath(self):
        assert self._sources_path != '<uninitialized>'
        return self._sources_path

    def maxJavaCompliance(self):
        """:rtype : JavaCompliance"""
        assert not self.suite.isBinarySuite()
        if not hasattr(self, '.maxJavaCompliance'):
            javaCompliances = [p.javaCompliance for p in self.archived_deps() if p.isJavaProject()]
            if self.javaCompliance is not None:
                javaCompliances.append(self.javaCompliance)
            if len(javaCompliances) > 0:
                setattr(self, '.maxJavaCompliance', max(javaCompliances))
            else:
                setattr(self, '.maxJavaCompliance', None)
        return getattr(self, '.maxJavaCompliance')

    def paths_to_clean(self):
        paths = [self.original_path(), self._stripped_path(), self.strip_mapping_file()]
        jdk = get_jdk(tag='default')
        if jdk.javaCompliance >= '9':
            info = get_java_module_info(self)
            if info:
                _, pickle_path, _ = info  # pylint: disable=unpacking-non-sequence
                paths.append(pickle_path)
        return paths

    def is_stripped(self):
        return _opts.strip_jars and self.stripConfig is not None

    def set_archiveparticipant(self, archiveparticipant):
        """
        Adds an object that participates in the `make_archive` method of this distribution.

        :param archiveparticipant: an object for which the following methods, if defined, will be called by `make_archive`:

            __opened__(arc, srcArc, services)
                Called when archiving starts. The `arc` and `srcArc` Archiver objects are for writing to the
                binary and source jars for the distribution. The `services` dict is for collating the files
                that will be written to ``META-INF/services`` in the binary jar. It is a map from service names
                to a list of providers for the named service. If services should be versioned, an integer can be used
                as a key and the value is a map from service names to a list of providers for this version.
            __add__(arcname, contents)
                Submits an entry for addition to the binary archive (via the `zf` ZipFile field of the `arc` object).
                Returns True if this object claims responsibility for adding/eliding `contents` to/from the archive,
                False otherwise (i.e., the caller must take responsibility for the entry).
            __addsrc__(arcname, contents)
                Same as `__add__` except that it targets the source archive.
            __closing__()
                Called just before the `services` are written to the binary archive and both archives are
                written to their underlying files.
        """
        if archiveparticipant not in self.archiveparticipants:
            if not hasattr(archiveparticipant, '__opened__'):
                abort(str(archiveparticipant) + ' must define __opened__')
            self.archiveparticipants.append(archiveparticipant)
        else:
            warn('registering archive participant ' + str(archiveparticipant) + ' for ' + str(self) + ' twice')

    def origin(self):
        return Dependency.origin(self)

    def classpath_repr(self, resolve=True):
        if resolve and not exists(self.path):
            abort("unbuilt distribution {} can not be on a class path. Did you forget to run 'mx build'?".format(self))
        return self.path

    def get_ide_project_dir(self):
        """
        Gets the directory in which the IDE project configuration for this distribution is generated.
        """
        if self.subDir:
            return join(self.suite.dir, self.subDir, self.name + '.dist')
        else:
            return join(self.suite.dir, self.name + '.dist')

    def make_archive(self):
        """
        Creates the jar file(s) defined by this JARDistribution.
        """
        if isinstance(self.suite, BinarySuite):
            return

        # are sources combined into main archive?
        unified = self.original_path() == self.sourcesPath
        snippetsPattern = None
        if hasattr(self.suite, 'snippetsPattern'):
            snippetsPattern = re.compile(self.suite.snippetsPattern)

        versioned_meta_inf_re = re.compile(r'META-INF/versions/([1-9][0-9]*)/META-INF/')

        services = {}
        manifestEntries = self.manifestEntries.copy()
        with Archiver(self.original_path()) as arc:
            with Archiver(None if unified else self.sourcesPath, compress=True) as srcArcRaw:
                srcArc = arc if unified else srcArcRaw

                for a in self.archiveparticipants:
                    a.__opened__(arc, srcArc, services)

                def participants__add__(arcname, contents, addsrc=False):
                    """
                    Calls the __add__ or __addsrc__ method on `self.archiveparticipants`, ensuring at most one participant claims
                    responsibility for adding/omitting `contents` under the name `arcname` to/from the archive.

                    :param str arcname: name in archive for `contents`
                    :params str contents: byte array to write to the archive under `arcname`
                    :return: True if a participant claimed responsibility, False otherwise
                    """
                    claimer = None
                    for a in self.archiveparticipants:
                        method = getattr(a, '__add__' if not addsrc else '__addsrc__', None)
                        if method:
                            if method(arcname, contents):
                                if claimer:
                                    abort('Archive participant ' + str(a) + ' cannot claim responsibility for ' + arcname + ' in ' +
                                          arc.path + ' as it was already claimed by ' + str(claimer))
                                claimer = a
                    return claimer is not None

                class ArchiveWriteGuard:
                    """
                    A scope for adding an entry to an archive. The addition should only be performed
                    if the scope object is not None when entered:
                    ```
                    with ArchiveWriteGuard(...) as guard:
                        if guard: <add entry to archive
                    ```
                    """
                    def __init__(self, path, zf, arcname, source, source_zf=None):
                        self.path = path
                        self.zf = zf
                        self.source_zf = source_zf
                        self.arcname = arcname
                        self.source = source
                        self._can_write = False

                    def __enter__(self):
                        arcname = self.arcname
                        source = self.source
                        if os.path.basename(arcname).startswith('.'):
                            logv('Excluding dotfile: ' + source)
                            return None
                        elif arcname == "META-INF/MANIFEST.MF":
                            if self.source_zf:
                                # Do not inherit the manifest from other jars
                                logv('Excluding META-INF/MANIFEST.MF from ' + source)
                                return None
                        if not hasattr(self.zf, '_provenance'):
                            self.zf._provenance = {}
                        existingSource = self.zf._provenance.get(arcname, None)
                        if existingSource and existingSource != source:
                            if arcname[-1] not in (os.path.sep, '/'):
                                if self.source_zf and self.source_zf.read(arcname) == self.zf.read(arcname):
                                    logv(self.path + ': file ' + arcname + ' is already present\n  new: ' + source + '\n  old: ' + existingSource)
                                else:
                                    warn(self.path + ': avoid overwrite of ' + arcname + '\n  new: ' + source + '\n  old: ' + existingSource)
                            return None
                        self._can_write = True
                        return self

                    def __exit__(self, exc_type, exc_value, traceback):
                        if self._can_write:
                            if self.arcname in self.zf.namelist():
                                self.zf._provenance[self.arcname] = self.source

                def addFromJAR(jarPath):
                    with zipfile.ZipFile(jarPath, 'r') as source_zf:
                        for info in source_zf.infolist():
                            arcname = info.filename
                            if arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/':
                                service = arcname[len('META-INF/services/'):]
                                assert '/' not in service
                                services.setdefault(service, []).extend(_decode(source_zf.read(arcname)).splitlines())
                            else:
                                with ArchiveWriteGuard(self.original_path(), arc.zf, arcname, jarPath + '!' + arcname, source_zf=source_zf) as guard:
                                    if guard:
                                        contents = source_zf.read(arcname)
                                        if not participants__add__(arcname, contents):
                                            if versioned_meta_inf_re.match(arcname):
                                                warn("META-INF resources can not be versioned ({} from {}). The resulting JAR will be invalid.".format(arcname, jarPath))
                                            # The JDK's ZipInputStream will fail to read files with a data descriptor written by python's zipfile
                                            info.flag_bits &= ~0x08
                                            arc.zf.writestr(info, contents)

                def addFile(outputDir, relpath, archivePrefix, arcnameCheck=None, includeServices=False):
                    arcname = join(archivePrefix, relpath).replace(os.sep, '/')
                    assert arcname[-1] != '/'
                    if arcnameCheck is not None and not arcnameCheck(arcname):
                        return
                    if relpath.startswith(join('META-INF', 'services')):
                        if includeServices:
                            service = basename(relpath)
                            assert dirname(relpath) == join('META-INF', 'services')
                            m = versioned_meta_inf_re.match(arcname)
                            if m:
                                service_version = int(m.group(1))
                                services_dict = services.setdefault(service_version, {})
                            else:
                                services_dict = services
                            with open(join(outputDir, relpath), 'r') as fp:
                                services_dict.setdefault(service, []).extend([provider.strip() for provider in fp.readlines()])
                    else:
                        if snippetsPattern and snippetsPattern.match(relpath):
                            return
                        source = join(outputDir, relpath)
                        with ArchiveWriteGuard(self.original_path(), arc.zf, arcname, source) as guard:
                            if guard:
                                with open(source, 'rb') as fp:
                                    contents = fp.read()
                                if not participants__add__(arcname, contents):
                                    if versioned_meta_inf_re.match(arcname):
                                        warn("META-INF resources can not be versioned ({}). The resulting JAR will be invalid.".format(source))
                                    info = zipfile.ZipInfo(arcname, time.localtime(getmtime(source))[:6])
                                    info.compress_type = arc.zf.compression
                                    info.external_attr = S_IMODE(stat(source).st_mode) << 16
                                    arc.zf.writestr(info, contents)

                def addSrcFromDir(srcDir, archivePrefix='', arcnameCheck=None):
                    for root, _, files in os.walk(srcDir):
                        relpath = root[len(srcDir) + 1:]
                        for f in files:
                            if f.endswith('.java'):
                                arcname = join(archivePrefix, relpath, f).replace(os.sep, '/')
                                if arcnameCheck is None or arcnameCheck(arcname):
                                    with ArchiveWriteGuard(self.original_path(), srcArc.zf, arcname, join(root, f)) as guard:
                                        if guard:
                                            with open(join(root, f), 'r') as fp:
                                                contents = fp.read()
                                            if not participants__add__(arcname, contents, addsrc=True):
                                                info = zipfile.ZipInfo(arcname, time.localtime(getmtime(join(root, f)))[:6])
                                                info.compress_type = arc.zf.compression
                                                info.external_attr = S_IMODE(stat(join(root, f)).st_mode) << 16
                                                srcArc.zf.writestr(info, contents)

                if self.mainClass:
                    if 'Main-Class' in manifestEntries:
                        abort("Main-Class is defined both as the 'mainClass': '" + self.mainClass + "' argument and in 'manifestEntries' as "
                              + manifestEntries['Main-Class'] + " of the " + self.name + " distribution. There should be only one definition.")
                    manifestEntries['Main-Class'] = self.mainClass

                # Overlay projects whose JDK version is less than 9 must be processed before the overlayed projects
                # as the overlay classes must be added to the jar instead of the overlayed classes. Overlays for
                # JDK 9 or later use the multi-release jar layout.
                head = [d for d in self.archived_deps() if d.isJavaProject() and d.javaCompliance.value < 9 and hasattr(d, 'overlayTarget')]
                tail = [d for d in self.archived_deps() if d not in head]

                # Map from JDK 8 or earlier overlays to the projects that define them
                overlays = {}

                for dep in head + tail:
                    if hasattr(dep, "doNotArchive") and dep.doNotArchive:
                        logv('[' + self.original_path() + ': ignoring project ' + dep.name + ']')
                        continue
                    if self.theLicense is not None and set(self.theLicense or []) < set(dep.theLicense or []):
                        if dep.suite.getMxCompatibility().supportsLicenses() and self.suite.getMxCompatibility().supportsLicenses():
                            report = abort
                        else:
                            report = warn
                        depLicense = [l.name for l in dep.theLicense] if dep.theLicense else ['??']
                        selfLicense = [l.name for l in self.theLicense] if self.theLicense else ['??']
                        report('Incompatible licenses: distribution {} ({}) can not contain {} ({})'.format(self.name, ', '.join(selfLicense), dep.name, ', '.join(depLicense)))
                    if dep.isLibrary() or dep.isJARDistribution():
                        if dep.isLibrary():
                            l = dep
                            # optional libraries and their dependents should already have been removed
                            assert not l.optional or l.is_available()
                            # merge library jar into distribution jar
                            logv('[' + self.original_path() + ': adding library ' + l.name + ']')
                            jarPath = l.get_path(resolve=True)
                            jarSourcePath = l.get_source_path(resolve=True)
                        elif dep.isJARDistribution():
                            logv('[' + self.original_path() + ': adding distribution ' + dep.name + ']')
                            jarPath = dep.path
                            jarSourcePath = dep.sourcesPath
                        else:
                            raise abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))
                        if jarPath:
                            addFromJAR(jarPath)
                        if srcArc.zf and jarSourcePath:
                            with zipfile.ZipFile(jarSourcePath, 'r') as source_zf:
                                for arcname in source_zf.namelist():
                                    with ArchiveWriteGuard(self.original_path(), srcArc.zf, arcname, jarPath + '!' + arcname, source_zf=source_zf) as guard:
                                        if guard:
                                            contents = source_zf.read(arcname)
                                            if not participants__add__(arcname, contents, addsrc=True):
                                                srcArc.zf.writestr(arcname, contents)
                    elif dep.isMavenProject():
                        logv('[' + self.original_path() + ': adding jar from Maven project ' + dep.name + ']')
                        addFromJAR(dep.classpath_repr())
                        for srcDir in dep.source_dirs():
                            addSrcFromDir(srcDir)
                    elif dep.isJavaProject():
                        p = dep
                        javaCompliance = self.maxJavaCompliance()
                        if javaCompliance:
                            if p.javaCompliance > javaCompliance:
                                abort("Compliance level doesn't match: Distribution {0} requires {1}, but {2} is {3}.".format(self.name, javaCompliance, p.name, p.javaCompliance), context=self)

                        logv('[' + self.original_path() + ': adding project ' + p.name + ']')
                        outputDir = p.output_dir()

                        archivePrefix = p.archive_prefix() if hasattr(p, 'archive_prefix') else ''
                        mrjVersion = getattr(p, 'multiReleaseJarVersion', None)
                        is_overlay = False
                        if mrjVersion is not None:
                            if p.javaCompliance.value < 9:
                                abort('Project with "multiReleaseJarVersion" attribute must have javaCompliance >= 9', context=p)
                            if archivePrefix:
                                abort("Project cannot have a 'multiReleaseJarVersion' attribute if it has an 'archivePrefix' attribute", context=p)
                            try:
                                mrjVersion = _parse_multireleasejar_version(mrjVersion)
                            except ArgumentTypeError as e:
                                abort(str(e), context=p)
                            archivePrefix = 'META-INF/versions/{}/'.format(mrjVersion)
                            manifestEntries['Multi-Release'] = 'true'
                        elif hasattr(p, 'overlayTarget'):
                            if p.javaCompliance.value > 8:
                                if p.suite.getMxCompatibility().automatic_overlay_distribution_deps:
                                    abort('Project with an "overlayTarget" attribute and javaCompliance >= 9 must also have a "multiReleaseJarVersion" attribute', context=p)
                                abort('Project with an "overlayTarget" attribute must have javaCompliance < 9', context=p)
                            is_overlay = True
                            if archivePrefix:
                                abort("Project cannot have a 'overlayTarget' attribute if it has an 'archivePrefix' attribute", context=p)

                        def overlay_check(arcname):
                            if is_overlay:
                                if arcname in overlays:
                                    abort('Overlay for {} is defined by more than one project: {} and {}'.format(arcname, p, overlays[arcname]))
                                overlays[arcname] = p
                                return True
                            else:
                                return arcname not in overlays

                        def addClasses(archivePrefix, includeServices):
                            for root, _, files in os.walk(outputDir):
                                reldir = root[len(outputDir) + 1:]
                                for f in files:
                                    relpath = join(reldir, f)
                                    addFile(outputDir, relpath, archivePrefix, arcnameCheck=overlay_check, includeServices=includeServices)

                        addClasses(archivePrefix, includeServices=True)
                        if srcArc.zf:
                            sourceDirs = p.source_dirs()
                            if p.source_gen_dir():
                                sourceDirs.append(p.source_gen_dir())
                            for srcDir in sourceDirs:
                                addSrcFromDir(srcDir, archivePrefix, arcnameCheck=overlay_check)

                        bounds = p.javaCompliance._bounds()
                        if len(bounds) == 4:
                            _, _, lower2, _ = bounds
                            if lower2 > 8:
                                # Make a multi-release-jar versioned copy of the class files
                                # for the lower bound of the second range in a disjoint compliance.
                                # Anything below that version will pick up the class files in the
                                # root directory of the jar.
                                if get_jdk(str(JavaCompliance(lower2)), cancel='probing'):
                                    archivePrefix = 'META-INF/versions/{}/'.format(lower2)
                                    addClasses(archivePrefix, includeServices=False)

                    elif dep.isArchivableProject():
                        logv('[' + self.original_path() + ': adding archivable project ' + dep.name + ']')
                        archivePrefix = dep.archive_prefix()
                        outputDir = dep.output_dir()
                        for f in dep.getResults():
                            relpath = dep.get_relpath(f, outputDir)
                            addFile(outputDir, relpath, archivePrefix)
                    else:
                        abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))

                if len(manifestEntries) != 0:
                    if 'Manifest-Version' not in manifestEntries:
                        manifest = 'Manifest-Version: 1.0' + '\n'
                    else:
                        manifest = 'Manifest-Version: ' + manifestEntries['Manifest-Version'] + '\n'
                        manifestEntries.pop('Manifest-Version')

                    for manifestKey, manifestValue in manifestEntries.items():
                        manifest = manifest + manifestKey + ': ' + manifestValue + '\n'

                    arc.zf.writestr("META-INF/MANIFEST.MF", manifest)
                for a in self.archiveparticipants:
                    if hasattr(a, '__closing__'):
                        a.__closing__()

                # accumulate services
                services_versions = sorted([v for v in services if isinstance(v, int)])
                if services_versions:
                    acummulated_services = {n: set(p) for n, p in services.items() if isinstance(n, str)}
                    for v in services_versions:
                        for service, providers in services[v].items():
                            providers_set = frozenset(providers)
                            accumulated_providers = acummulated_services.setdefault(service, set())
                            missing = accumulated_providers - providers_set
                            accumulated_providers.update(providers_set)
                            if missing:
                                warn("Adding {} for {} at version {}".format(missing, service, v))
                                services[v][service] = frozenset(accumulated_providers)

                def add_service_providers(service, providers, archive_prefix=''):
                    arcname = archive_prefix + 'META-INF/services/' + service
                    # Convert providers to a set before printing to remove duplicates
                    arc.zf.writestr(arcname, '\n'.join(frozenset(providers)) + '\n')

                for service_or_version, providers in services.items():
                    if isinstance(service_or_version, int):
                        services_version = service_or_version
                        for service, providers_ in providers.items():
                            add_service_providers(service, providers_, 'META-INF/_versions/' + str(services_version) + '/')
                    else:
                        add_service_providers(service_or_version, providers)

        self.notify_updated()

        compliance = self._compliance_for_build()
        if compliance >= '9':
            jmd = make_java_module(self, get_jdk(compliance))
            if jmd:
                setattr(self, '.javaModule', jmd)

        if self.is_stripped():
            self.strip_jar()

    _strip_map_file_suffix = '.map'
    _strip_cfg_deps_file_suffix = '.conf.d'

    def strip_mapping_file(self):
        return self._stripped_path() + JARDistribution._strip_map_file_suffix

    def strip_config_dependency_file(self):
        return self._stripped_path() + JARDistribution._strip_cfg_deps_file_suffix

    def strip_jar(self):
        assert _opts.strip_jars, "Only works under the flag --strip-jars"

        jdk = get_jdk(self.maxJavaCompliance())
        if jdk.javaCompliance >= '11':
            abort('Cannot strip {} - ProGuard does not yet support JDK {}'.format(self, jdk.javaCompliance))

        logv('Stripping {}...'.format(self.name))
        jdk9_or_later = jdk.javaCompliance >= '9'
        strip_command = ['-jar', library('PROGUARD_6_0_3').get_path(resolve=True)]

        with tempfile.NamedTemporaryFile(delete=False, suffix=JARDistribution._strip_map_file_suffix) as config_tmp_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=JARDistribution._strip_map_file_suffix) as mapping_tmp_file:
                # add config files from projects
                assert all((os.path.isabs(f) for f in self.stripConfig))
                # add mapping files
                assert all((os.path.isabs(f) for f in self.stripMapping))

                # add configs (must be one file)
                _merge_file_contents(self.stripConfig, config_tmp_file)
                strip_command += ['-include', config_tmp_file.name]

                # input and output jars
                input_maps = self.stripMapping + [d.strip_mapping_file() for d in classpath_entries(self, includeSelf=False) if d.isJARDistribution() and d.is_stripped()]

                if not jdk9_or_later:
                    libraryjars = classpath(self, includeSelf=False, includeBootClasspath=True, jdk=jdk, unique=True, ignoreStripped=True).split(os.pathsep)
                else:
                    # Override modules from the JDK with those from dependencies
                    entries = classpath_entries(self, includeSelf=False)
                    dep_modules = set()
                    for e in entries:
                        if e.isJARDistribution():
                            info = get_java_module_info(e)
                            if info:
                                modulename, _, _ = info  # pylint: disable=unpacking-non-sequence
                                dep_modules.add(modulename)
                    libraryjars = classpath(self, includeSelf=False, includeBootClasspath=False, jdk=jdk, unique=True, ignoreStripped=True).split(os.pathsep) + \
                        [join(jdk.home, 'jmods', jmd.name + '.jmod') for jmd in jdk.get_modules() if jmd.name not in dep_modules]

                # Ignored versioned class files until multi-release jars are
                # supported by ProGuard (https://sourceforge.net/p/proguard/bugs/671/)
                strip_command += [
                     '-injars', self.original_path() + '(!META-INF/versions/**,!module-info.class)',
                     '-outjars', self.path, # only the jar of this distribution
                     '-libraryjars', os.pathsep.join([e + '(!META-INF/versions/**,!module-info.class)' for e in libraryjars]),
                     '-printmapping', self.strip_mapping_file(),
                ]

                # options for incremental stripping
                strip_command += ['-dontoptimize', '-dontshrink', '-useuniqueclassmembernames']

                # common options for all projects
                strip_command += [
                    '-adaptclassstrings',
                    '-adaptresourcefilecontents', 'META-INF/services/*',
                    '-adaptresourcefilenames', 'META-INF/services/*',
                    '-renamesourcefileattribute', 'stripped',
                    '-keepattributes', 'Exceptions,InnerClasses,Signature,Deprecated,SourceFile,LineNumberTable,RuntimeVisible*Annotations,EnclosingMethod,AnnotationDefault',
                ]

                # add mappings of all stripped dependencies (must be one file)
                if input_maps:
                    _merge_file_contents(input_maps, mapping_tmp_file)
                    strip_command += ['-applymapping', mapping_tmp_file.name]

                if _opts.very_verbose:
                    strip_command.append('-verbose')
                elif not (_opts.verbose or is_windows()):
                    strip_command += ['-dontnote', '**']

                run_java(strip_command, jdk=jdk)
                with open(self.strip_config_dependency_file(), 'w') as f:
                    f.writelines((l + os.linesep for l in self.stripConfig))

    def remoteName(self, platform=None):
        base_name = super(JARDistribution, self).remoteName(platform=platform)
        if self.is_stripped():
            return base_name + "_stripped"
        else:
            return base_name

    def getBuildTask(self, args):
        return JARArchiveTask(args, self)

    def exists(self):
        return exists(self.path) and not self.sourcesPath or exists(self.sourcesPath) #pylint: disable=consider-using-ternary

    def remoteExtension(self):
        return 'jar'

    def localExtension(self):
        return 'jar'

    def getArchivableResults(self, use_relpath=True, single=False):
        yield self.path, self.default_filename()
        if not single:
            if self.sourcesPath:
                yield self.sourcesPath, self.default_source_filename()
            if self.is_stripped():
                yield self.strip_mapping_file(), self.default_filename() + JARDistribution._strip_map_file_suffix

    def needsUpdate(self, newestInput):
        res = _needsUpdate(newestInput, self.path)
        if res:
            return res
        if self.sourcesPath:
            res = _needsUpdate(newestInput, self.sourcesPath)
            if res:
                return res
        if self.suite.isBinarySuite():
            return None
        if self._compliance_for_build() >= '9':
            info = get_java_module_info(self)
            if info:
                _, pickle_path, _ = info  # pylint: disable=unpacking-non-sequence
                res = _needsUpdate(newestInput, pickle_path)
                if res:
                    return res
                res = _needsUpdate(self.path, pickle_path)
                if res:
                    return res
        if self.is_stripped():
            previous_strip_configs = []
            dependency_file = self.strip_config_dependency_file()
            if exists(dependency_file):
                with open(dependency_file) as f:
                    previous_strip_configs = (l.rstrip('\r\n') for l in f.readlines())
            if set(previous_strip_configs) != set(self.stripConfig):
                return 'strip config files changed'
            for f in self.stripConfig:
                ts = TimeStampFile(f)
                if ts.isNewerThan(self.path):
                    return '{} is newer than {}'.format(ts, self.path)
        return None

class JMHArchiveParticipant:
    """ Archive participant for building JMH benchmarking jars. """

    def __init__(self, dist):
        if not dist.mainClass:
            # set default JMH main class
            dist.mainClass = "org.openjdk.jmh.Main"

    def __opened__(self, arc, srcArc, services):
        self.arc = arc
        self.meta_files = {
            'META-INF/BenchmarkList': None,
            'META-INF/CompilerHints': None,
        }

    def __add__(self, arcname, contents): #pylint: disable=unexpected-special-method-signature
        if arcname in self.meta_files:
            if self.meta_files[arcname] is None:
                self.meta_files[arcname] = contents
            else:
                self.meta_files[arcname] += contents
            return True
        return False

    def __addsrc__(self, arcname, contents):
        return False

    def __closing__(self):
        for filename, content in self.meta_files.items():
            if content is not None:
                self.arc.zf.writestr(filename, content)


class AbstractArchiveTask(BuildTask):
    __metaclass__ = ABCMeta

    def __init__(self, args, dist):
        BuildTask.__init__(self, dist, args, 1)

    def needsBuild(self, newestInput):
        sup = BuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        reason = self.subject.needsUpdate(newestInput)
        if reason:
            return True, reason
        return False, None

    def build(self):
        self.subject.make_archive()

    def __str__(self):
        return "Archiving {}".format(self.subject.name)

    def buildForbidden(self):
        if super(AbstractArchiveTask, self).buildForbidden():
            return True
        return isinstance(self.subject.suite, BinarySuite)

    def cleanForbidden(self):
        if super(AbstractArchiveTask, self).cleanForbidden():
            return True
        return isinstance(self.subject.suite, BinarySuite)


class JARArchiveTask(AbstractArchiveTask):
    def buildForbidden(self):
        if super(JARArchiveTask, self).buildForbidden():
            return True
        if not self.args.java:
            return True
        return False

    def newestOutput(self):
        return TimeStampFile.newest([self.subject.path, self.subject.sourcesPath])

    def clean(self, forBuild=False):
        if isinstance(self.subject.suite, BinarySuite):  # make sure we never clean distributions from BinarySuites
            abort('should not reach here')
        for path in self.subject.paths_to_clean():
            if exists(path):
                os.remove(path)
        if self.subject.sourcesPath and exists(self.subject.sourcesPath):
            os.remove(self.subject.sourcesPath)

    def cleanForbidden(self):
        if super(JARArchiveTask, self).cleanForbidden():
            return True
        if not self.args.java:
            return True
        return False


class AbstractDistribution(Distribution):
    __metaclass__ = ABCMeta

    def __init__(self, suite, name, deps, path, excludedLibs, platformDependent, theLicense, output, **kwArgs):
        super(AbstractDistribution, self).__init__(suite, name, deps, excludedLibs, platformDependent, theLicense, **kwArgs)
        self.path = _make_absolute(path.replace('/', os.sep) if path else self._default_path(), suite.dir)
        self.output = output

    def get_output(self):
        if self.output:
            return join(self.suite.dir, self.output)
        return None

    def exists(self):
        return exists(self.path)

    def getArchivableResults(self, use_relpath=True, single=False):
        yield self.path, self.default_filename()

    def needsUpdate(self, newestInput):
        path_up = _needsUpdate(newestInput, self.path)
        if path_up:
            return path_up
        if self.output:
            output_up = _needsUpdate(newestInput, self.get_output())
            if output_up:
                return output_up
        return None

    def getBuildTask(self, args):
        return DefaultArchiveTask(args, self)


class AbstractTARDistribution(AbstractDistribution):
    __metaclass__ = ABCMeta
    __gzip_binary = None

    def remoteExtension(self):
        return 'tar.gz'

    def localExtension(self):
        return 'tar'

    def postPull(self, f):
        assert f.endswith('.gz')
        logv('Uncompressing {}...'.format(f))
        tarfilename = f[:-len('.gz')]
        if AbstractTARDistribution._has_gzip():
            with open(tarfilename, 'wb') as tar:
                # force, quiet, decompress, cat to stdout
                run([AbstractTARDistribution._gzip_binary(), '-f', '-q', '-d', '-c', f], out=tar)
        else:
            with gzip.open(f, 'rb') as gz, open(tarfilename, 'wb') as tar:
                shutil.copyfileobj(gz, tar)
        os.remove(f)
        if self.output:
            output = self.get_output()
            with tarfile.open(tarfilename, 'r:') as tar:
                logv('Extracting {} to {}'.format(tarfilename, output))
                tar.extractall(output)
        return tarfilename

    def prePush(self, f):
        tgz = f + '.gz'
        logv('Compressing {}...'.format(f))
        if AbstractTARDistribution._has_gzip():
            with open(tgz, 'wb') as tar:
                # force, quiet, cat to stdout
                run([AbstractTARDistribution._gzip_binary(), '-f', '-q', '-c', f], out=tar)
        else:
            with gzip.open(tgz, 'wb') as gz, open(f, 'rb') as tar:
                shutil.copyfileobj(tar, gz)
        return tgz

    @staticmethod
    def _gzip_binary():
        if not AbstractTARDistribution._has_gzip():
            abort("No gzip binary could be found")
        return AbstractTARDistribution.__gzip_binary

    @staticmethod
    def _has_gzip():
        if AbstractTARDistribution.__gzip_binary is None:
            # Probe for pigz (parallel gzip) first and then try common gzip
            for binary_name in ["pigz", "gzip"]:
                gzip_ret_code = None
                try:
                    gzip_ret_code = run([binary_name, '-V'], nonZeroIsFatal=False, err=subprocess.STDOUT, out=OutputCapture())
                except OSError as e:
                    gzip_ret_code = e
                if gzip_ret_code == 0:
                    AbstractTARDistribution.__gzip_binary = binary_name
                    break
        return AbstractTARDistribution.__gzip_binary is not None


class AbstractJARDistribution(AbstractDistribution, ClasspathDependency):
    __metaclass__ = ABCMeta

    def remoteExtension(self):
        return 'jar'

    def localExtension(self):
        return 'jar'

    def classpath_repr(self, resolve=True):
        return self.path

    @abstractmethod
    def compress_locally(self):
        pass

    @abstractmethod
    def compress_remotely(self):
        pass

    def postPull(self, f):
        if self.compress_locally() or not self.compress_remotely():
            return None
        logv('Uncompressing {}...'.format(f))
        tmp_dir = mkdtemp(".jar", self.name)
        with zipfile.ZipFile(f) as zf:
            zf.extractall(tmp_dir)
        tmp_fd, tmp_file = mkstemp(".jar", self.name)
        with os.fdopen(tmp_fd, 'w') as tmp_f, zipfile.ZipFile(tmp_f, 'w', compression=zipfile.ZIP_STORED) as zf:
            for root, _, files in os.walk(tmp_dir):
                arc_dir = os.path.relpath(root, tmp_dir)
                for f_ in files:
                    zf.write(join(root, f_), join(arc_dir, f_))
        rmtree(tmp_dir)
        return tmp_file

    def prePush(self, f):
        if not self.compress_remotely() or self.compress_locally():
            return f
        logv('Compressing {}...'.format(f))
        tmpdir = mkdtemp(".jar", self.name)
        with zipfile.ZipFile(f) as zf:
            zf.extractall(tmpdir)
        tmp_fd, tmp_file = mkstemp(".jar", self.name)
        with os.fdopen(tmp_fd, 'w') as tmp_f, zipfile.ZipFile(tmp_f, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                arc_dir = os.path.relpath(root, tmpdir)
                for f_ in files:
                    zf.write(join(root, f_), join(arc_dir, f_))
        rmtree(tmpdir)
        return tmp_file


class NativeTARDistribution(AbstractTARDistribution):
    """
    A distribution dependencies are only `NativeProject`s. It packages all the resources specified by
    `NativeProject.getResults` and `NativeProject.headers` for each constituent project.

    :param Suite suite: the suite in which the distribution is defined
    :param str name: the name of the distribution which must be unique across all suites
    :param list deps: the `NativeProject` dependencies of the distribution
    :param bool platformDependent: specifies if the built artifact is platform dependent
    :param str theLicense: license applicable when redistributing the built artifact of the distribution
    :param bool relpath: specifies if the names of tar file entries should be relative to the output
           directories of the constituent native projects' output directories
    :param str output: specifies where the content of the distribution should be copied upon creation
           or extracted after pull
    :param bool auto_prefix: specifies if the names of tar file entries from constituent
           platform dependent projects should be prefixed with `<os>-<arch>`

    Attributes:
        path: suite-local path to where the tar file will be placed
    """

    def __init__(self, suite, name, deps, path, excludedLibs, platformDependent, theLicense, relpath, output,
                 auto_prefix=False, **kwArgs):
        super(NativeTARDistribution, self).__init__(suite, name, deps, path, excludedLibs, platformDependent,
                                                    theLicense, output, **kwArgs)
        assert not auto_prefix or relpath, "{}: 'auto_prefix' requires 'relpath'".format(name)
        self.relpath = relpath
        if self.output is not None:
            self.output = mx_subst.results_substitutions.substitute(self.output, dependency=self)
        self.auto_prefix = auto_prefix

    def make_archive(self):
        ensure_dirname_exists(self.path)

        if self.output:
            output_path = self.get_output()
            if exists(output_path):
                os.utime(output_path, None)

        with Archiver(self.path, kind='tar') as arc:
            files = set()

            def archive_and_copy(name, arcname):
                assert arcname not in files, arcname
                files.add(arcname)

                arc.zf.add(name, arcname=arcname)

                if self.output:
                    dest = join(self.get_output(), arcname)
                    # Make path separators consistent for string compare
                    dest = normpath(dest)
                    name = normpath(name)
                    if name != dest:
                        ensure_dirname_exists(dest)
                        shutil.copy2(name, dest)

            for d in self.archived_deps():
                if d.isNativeProject() or d.isArchivableProject():
                    arc_prefix = ''
                    if self.auto_prefix and d.isPlatformDependent():
                        arc_prefix = self.platformName().replace('_', '-')
                    for file_path, arc_name in d.getArchivableResults(self.relpath):
                        archive_and_copy(file_path, join(arc_prefix, arc_name))
                elif hasattr(d, 'getResults') and not d.getResults():
                    logv("[{}: ignoring dependency {} with no results]".format(self.name, d.name))
                else:
                    abort('Unsupported dependency for native distribution {}: {}'.format(self.name, d.name))

        self.notify_updated()


class DefaultArchiveTask(AbstractArchiveTask):
    def newestOutput(self):
        return TimeStampFile(self.subject.path)

    def buildForbidden(self):
        if AbstractArchiveTask.buildForbidden(self):
            return True
        if not self.args.native:
            return True

    def clean(self, forBuild=False):
        if isinstance(self.subject.suite, BinarySuite):  # make sure we never clean distributions from BinarySuites
            abort('should not reach here')
        if exists(self.subject.path):
            os.remove(self.subject.path)
        if self.subject.output and (self.clean_output_for_build() or not forBuild) and self.subject.output != '.':
            output_dir = self.subject.get_output()
            if exists(output_dir):
                rmtree(output_dir)

    def clean_output_for_build(self):
        # some distributions have `output` set to the same directory as their input or to some directory that contains other files
        return False

    def cleanForbidden(self):
        if AbstractArchiveTask.cleanForbidden(self):
            return True
        if not self.args.native:
            return True
        return False


class LayoutArchiveTask(DefaultArchiveTask):
    def clean_output_for_build(self):
        return True

    def needsBuild(self, newestInput):
        sup = super(LayoutArchiveTask, self).needsBuild(newestInput)
        if sup[0]:
            return sup
        # TODO check for *extra* files that should be removed in `output`
        return False, None


class LayoutDistribution(AbstractDistribution):
    __metaclass__ = ABCMeta
    _linky = AbstractDistribution

    def __init__(self, suite, name, deps, layout, path, platformDependent, theLicense, excludedLibs=None, path_substitutions=None, string_substitutions=None, archive_factory=None, compress=False, **kw_args):
        """
        See docs/layout-distribution.md
        :type layout: dict[str, str]
        :type path_substitutions: mx_subst.SubstitutionEngine
        :type string_substitutions: mx_subst.SubstitutionEngine
        """
        super(LayoutDistribution, self).__init__(suite, name, deps, path, excludedLibs or [], platformDependent, theLicense, output=None, **kw_args)
        self.buildDependencies += LayoutDistribution._extract_deps(layout, suite, name)
        self.output = join(self.get_output_base(), name)  # initialized here rather than passed above since `get_output_base` is not ready before the super constructor
        self.layout = layout
        self.path_substitutions = path_substitutions or mx_subst.path_substitutions
        self.string_substitutions = string_substitutions or mx_subst.string_substitutions
        self._source_location_cache = {}
        self.archive_factory = archive_factory or Archiver
        self.compress = compress
        self._removed_deps = set()

    def getBuildTask(self, args):
        return LayoutArchiveTask(args, self)

    def removeDependency(self, d):
        super(LayoutDistribution, self).removeDependency(d)
        self._removed_deps.add(d.qualifiedName())
        if d.suite == self.suite:
            self._removed_deps.add(d.name)

    @staticmethod
    def _is_linky(path=None):
        if LayoutDistribution._linky is AbstractDistribution:
            value = get_env('LINKY_LAYOUT')
            if value is None:
                LayoutDistribution._linky = None
            else:
                if is_windows():
                    raise abort("LINKY_LAYOUT is not supported on Windows")
                LayoutDistribution._linky = re.compile(fnmatch.translate(value))
        if not LayoutDistribution._linky:
            return False
        if path is None:
            return True
        return LayoutDistribution._linky.match(path)

    @staticmethod
    def _extract_deps(layout, suite, distribution_name):
        deps = set()
        for _, source in LayoutDistribution._walk_static_layout(layout, distribution_name, context=suite):
            if 'dependency' in source:
                deps.add(source['dependency'])
        return sorted(deps)

    @staticmethod
    def _as_source_dict(source, distribution_name, destination, path_substitutions=None, string_substitutions=None, distribution_object=None, context=None):
        if isinstance(source, str):
            if ':' not in source:
                abort("Invalid source '{}' in layout for '{}': should be of the form '<type>:<specification>'\n"
                      "Type could be `file`, `string`, `link`, `dependency` or `extracted-dependency`.".format(source, distribution_name), context=context)
            source_type, source_spec = source.split(':', 1)
            source_dict = {
                "source_type": source_type,
                "_str_": source,
            }
            if source_type in ('dependency', 'extracted-dependency', 'skip'):
                if '/' in source_spec:
                    source_dict["dependency"], source_dict["path"] = source_spec.split('/', 1)
                else:
                    source_dict["dependency"], source_dict["path"] = source_spec, None
                source_dict["optional"] = False
            elif source_type == 'file':
                source_dict["path"] = source_spec
            elif source_type == 'link':
                source_dict["path"] = source_spec
            elif source_type == 'string':
                source_dict["value"] = source_spec
            else:
                abort("Unsupported source type: '{}' in '{}'".format(source_type, destination), context=context)
        else:
            source_dict = source
            source_type = source_dict['source_type']
            # TODO check structure
            if source_type in ('dependency', 'extracted-dependency'):
                source_dict['_str_'] = source_type + ":" + source_dict['dependency']
                if source_dict['path']:
                    source_dict['_str_'] += '/{}'.format(source_dict['path'])
                if 'optional' not in source_dict:
                    source_dict["optional"] = False
            elif source_type == 'file':
                source_dict['_str_'] = "file:" + source_dict['path']
            elif source_type == 'link':
                source_dict['_str_'] = "link:" + source_dict['path']
            elif source_type == 'string':
                source_dict['_str_'] = "string:" + source_dict['value']
        if 'exclude' in source_dict:
            if isinstance(source_dict['exclude'], str):
                source_dict['exclude'] = [source_dict['exclude']]
        if path_substitutions and source_dict.get("path"):
            source_dict["path"] = mx_subst.as_engine(path_substitutions).substitute(source_dict["path"], distribution=distribution_object)
        if string_substitutions and source_dict.get("value") and not source_dict.get("ignore_value_subst"):
            source_dict["value"] = mx_subst.as_engine(string_substitutions).substitute(source_dict["value"], distribution=distribution_object)
        return source_dict

    @staticmethod
    def _walk_static_layout(layout, distribution_name, path_substitutions=None, string_substitutions=None, distribution_object=None, context=None):
        substs = mx_subst.as_engine(path_substitutions) if path_substitutions else None
        for destination, sources in layout.items():
            if not isinstance(sources, list):
                sources = [sources]
            for source in sources:
                source_dict = LayoutTARDistribution._as_source_dict(source, distribution_name, destination, path_substitutions, string_substitutions, distribution_object, context)
                if substs:
                    destination = substs.substitute(destination)
                yield destination, source_dict

    def _walk_layout(self):
        for (destination, source_dict) in LayoutTARDistribution._walk_static_layout(self.layout, self.name, self.path_substitutions, self.string_substitutions, self, self):
            dep = source_dict.get("dependency")
            if dep not in self._removed_deps:
                yield (destination, source_dict)

    def _install_source(self, source, output, destination, archiver):
        clean_destination = destination
        if destination.startswith('./'):
            clean_destination = destination[2:]
        absolute_destination = join(output, clean_destination.replace('/', os.sep))
        source_type = source['source_type']
        provenance = "{}<-{}".format(destination, source['_str_'])

        def add_symlink(source_file, src, abs_dest, archive_dest, archive=True):
            destination_directory = dirname(abs_dest)
            ensure_dir_exists(destination_directory)
            resolved_output_link_target = normpath(join(destination_directory, src))
            if archive:
                if not resolved_output_link_target.startswith(output):
                    raise abort("Cannot add symlink that escapes the archive: link from '{}' would point to '{}' which is not in '{}'".format(source_file, resolved_output_link_target, output), context=self)
                archiver.add_link(src, archive_dest, provenance)
            if is_windows():
                def strip_suffix(path):
                    return os.path.splitext(path)[0]
                abs_dest = strip_suffix(abs_dest) + '.cmd'
            if lexists(abs_dest):
                # Since the `archiver.add_link` above already does "the right thing" regarding duplicates (warn or abort) here we just delete the existing file
                os.remove(abs_dest)
            if is_windows():
                link_template_name = join(_mx_suite.mxDir, 'exe_link_template.cmd')
                with open(link_template_name, 'r') as template, SafeFileCreation(abs_dest) as sfc, open(sfc.tmpPath, 'w') as link:
                    _template_subst = mx_subst.SubstitutionEngine(mx_subst.string_substitutions)
                    _template_subst.register_no_arg('target', normpath(strip_suffix(src)))
                    for line in template:
                        link.write(_template_subst.substitute(line))
            else:
                os.symlink(src, abs_dest)

        def merge_recursive(src, dst, src_arcname, excludes, archive=True):
            """
            Copies `src` to `dst`. If `src` is a directory copies recursively.
            """
            if glob_match_any(excludes, src_arcname):
                return
            absolute_destination = _safe_path(join(output, dst))
            if islink(src):
                link_target = os.readlink(src)
                if archive and isabs(link_target):
                    abort("Cannot add absolute links into archive: '{}' points to '{}'".format(src, link_target), context=self)
                add_symlink(src, link_target, absolute_destination, dst, archive=archive)
            elif isdir(src):
                ensure_dir_exists(absolute_destination, lstat(src).st_mode)
                for name in os.listdir(src):
                    merge_recursive(join(src, name), join(dst, name), join(src_arcname, name), excludes, archive=archive)
            else:
                ensure_dir_exists(dirname(absolute_destination))
                if archive:
                    archiver.add(src, dst, provenance)
                if LayoutDistribution._is_linky(absolute_destination):
                    if lexists(absolute_destination):
                        os.remove(absolute_destination)
                    os.symlink(os.path.relpath(src, dirname(absolute_destination)), absolute_destination)
                else:
                    shutil.copy(src, absolute_destination)

        def _install_source_files(files, include=None, excludes=None, optional=False, archive=True):
            excludes = excludes or []
            if destination.endswith('/'):
                ensure_dir_exists(absolute_destination)
            first_file = True
            for _source_file, _arcname in files:
                matched = ''
                if include is not None:
                    matched = glob_match(include, _arcname)
                    if matched is None:
                        continue
                if islink(_source_file):
                    _source_file = join(dirname(_source_file), os.readlink(_source_file))
                if destination.endswith('/'):
                    strip_prefix = dirname(matched)
                    name = _arcname
                    if strip_prefix:
                        name = name[len(strip_prefix) + 1:]
                    _dst = join(clean_destination, name)
                else:
                    _dst = clean_destination
                    if not first_file:
                        abort("Unexpected source for '{dest}' expected one file but got multiple.\n"
                              "Either use a directory destination ('{dest}/') or change the source".format(dest=destination), context=self)
                merge_recursive(_source_file, _dst, _arcname, excludes, archive=archive)
                first_file = False
            if first_file and not optional:
                abort("Could not find any source file for '{}'".format(source['_str_']), context=self)

        if source_type == 'dependency':
            d = dependency(source['dependency'], context=self)
            if_stripped = source.get('if_stripped')
            if if_stripped is not None and d.isJARDistribution():
                if if_stripped not in ('include', 'exclude'):
                    abort("Could not understand `if_stripped` value '{}'. Valid values are 'include' and 'exclude'".format(if_stripped), context=self)
                if (if_stripped == 'exclude' and d.is_stripped()) or (if_stripped == 'include' and not d.is_stripped()):
                    return
            if source.get('path') is None:
                try:
                    _install_source_files([next(d.getArchivableResults(single=True))])
                except ValueError as e:
                    assert e.message == 'single not supported'
                    msg = "Can not use '{}' of type {} without a path.".format(d.name, d.__class__.__name__)
                    if destination.endswith('/'):
                        msg += "\nDid you mean '{}/*'".format(source['_str_'])
                    else:
                        msg += "\nUse the '{}/<path>' format".format(source['_str_'])
                    abort(msg)
            else:
                _install_source_files((
                    (source_file, arcname) for source_file, arcname in d.getArchivableResults()
                ), include=source['path'], excludes=source.get('exclude'), optional=source['optional'])
        elif source_type == 'extracted-dependency':
            path = source['path']
            exclude = source.get('exclude', [])
            d = dependency(source['dependency'], context=self)
            try:
                source_archive_file, _ = next(d.getArchivableResults(single=True))
            except ValueError as e:
                assert e.message == 'single not supported'
                raise abort("Can not use '{}' of type {} for an 'extracted-dependency' ('{}').".format(d.name, d.__class__.__name__, destination))

            unarchiver_dest_directory = absolute_destination
            if not destination.endswith('/'):
                if path is None:
                    abort("Invalid source '{type}:{dependency}' used in destination '{dest}':\n"
                          "When using 'extracted-dependency' to extract to a single file, a path must be specified. Did you mean\n"
                          " - '{dest}/' as a destination (i.e., extracting all files from '{dependency}' into {dest})\n"
                          " - or '{type}:{dependency}/path/to/file/in/archive' as a source (i.e., extracting /path/to/file/in/archive from '{dependency}' to '{dest}')".format(
                            dest=destination,
                            dependency=d.name,
                            type=source_type),
                        context=self)
                unarchiver_dest_directory = dirname(unarchiver_dest_directory)
            ensure_dir_exists(unarchiver_dest_directory)
            ext = get_file_extension(source_archive_file)
            output_done = False
            if isinstance(d, LayoutDistribution) and LayoutDistribution._is_linky():
                _out_dir = d.get_output()
                _prefix = join(_out_dir, '')
                if path:
                    file_path = join(_out_dir, path)
                else:
                    file_path = _out_dir

                def _rel_name(_source_file):
                    assert _source_file.startswith(_prefix) or _source_file == _prefix[:-1]
                    return _source_file[len(_prefix):]
                _install_source_files(((source_file, _rel_name(source_file)) for source_file in glob.iglob(file_path)), include=path, excludes=exclude, archive=False)
                output_done = True

            first_file_box = [True]
            dest_arcname_prefix = os.path.relpath(unarchiver_dest_directory, output).replace(os.sep, '/')

            def dest_arcname(src_arcname):
                if not dest_arcname_prefix:
                    return src_arcname
                return dest_arcname_prefix + '/' + src_arcname

            def _filter_archive_name(name):
                _root_match = False
                if path is not None:
                    matched = glob_match(path, name)
                    if not matched:
                        return None, False
                    if glob_match_any(exclude, name):
                        return None, False
                    _root_match = len(matched.split('/')) == len(name.split('/'))
                    strip_prefix = dirname(matched)
                    if strip_prefix:
                        name = name[len(strip_prefix) + 1:]
                if not destination.endswith('/'):
                    name = '/'.join(name.split('/')[:-1] + [basename(destination)])
                    if not first_file_box[0]:
                        abort("Unexpected source for '{dest}' expected one file but got multiple.\n"
                              "Either use a directory destination ('{dest}/') or change the source".format(dest=destination), context=self)
                first_file_box[0] = False
                return name, _root_match

            with TempDir() if output_done else NoOpContext(unarchiver_dest_directory) as unarchiver_dest_directory:
                if ext.endswith('zip') or ext.endswith('jar'):
                    with zipfile.ZipFile(source_archive_file) as zf:
                        for zipinfo in zf.infolist():
                            zipinfo.filename, _ = _filter_archive_name(zipinfo.filename)
                            if not zipinfo.filename:
                                continue
                            extracted_file = zf.extract(zipinfo, unarchiver_dest_directory)
                            unix_attributes = (zipinfo.external_attr >> 16) & 0xFFFF
                            if unix_attributes != 0:
                                os.chmod(extracted_file, unix_attributes)
                            archiver.add(extracted_file, dest_arcname(zipinfo.filename), provenance)
                elif 'tar' in ext or ext.endswith('tgz'):
                    with tarfile.TarFile.open(source_archive_file) as tf:
                        # from tarfile.TarFile.extractall:
                        directories = []
                        for tarinfo in tf:
                            tarinfo.name, root_match = _filter_archive_name(tarinfo.name.rstrip("/"))
                            if not tarinfo.name:
                                continue
                            extracted_file = join(unarchiver_dest_directory, tarinfo.name.replace("/", os.sep))
                            arcname = dest_arcname(tarinfo.name)
                            if tarinfo.issym():
                                if root_match:
                                    tf._extract_member(tf._find_link_target(tarinfo), extracted_file)
                                    archiver.add(extracted_file, arcname, provenance)
                                else:
                                    tf.extract(tarinfo, unarchiver_dest_directory)
                                    archiver.add_link(tarinfo.linkname, arcname, provenance)
                            else:
                                tf.extract(tarinfo, unarchiver_dest_directory)
                                archiver.add(extracted_file, arcname, provenance)
                                if tarinfo.isdir():
                                    # use a safe mode while extracting, fix later
                                    os.chmod(extracted_file, 0o700)
                                    directories.append(tarinfo)

                        # Reverse sort directories.
                        directories.sort(key=operator.attrgetter('name'))
                        directories.reverse()

                        # Set correct owner, mtime and filemode on directories.
                        for tarinfo in directories:
                            dirpath = join(absolute_destination, tarinfo.name)
                            try:
                                tf.chown(tarinfo, dirpath)
                                tf.utime(tarinfo, dirpath)
                                tf.chmod(tarinfo, dirpath)
                            except tarfile.ExtractError as e:
                                abort("tarfile: " + str(e))
                else:
                    abort("Unsupported file type in 'extracted-dependency' for {}: '{}'".format(destination, source_archive_file))
                if first_file_box[0] and path is not None and not source['optional']:
                    abort("Could not find any source file for '{}'".format(source['_str_']), context=self)
        elif source_type == 'file':
            files_root = self.suite.dir
            source_path = source['path']
            if source_path.startswith(self.suite.dir):
                source_path = source_path[len(self.suite.dir) + 1:]
            file_path = normpath(join(self.suite.dir, source_path))

            def _rel_arcname(_source_file):
                return os.path.relpath(_source_file, files_root)
            _arcname_f = _rel_arcname
            if not self.suite.vc.locate(self.suite.vc_dir, file_path, abortOnError=False):
                absolute_source = isabs(source_path)
                if absolute_source:
                    _arcname_f = lambda a: a
                warn("Adding file which is not in the repository: '{}' in '{}'".format(file_path, destination), context=self)
            elif isabs(source_path):
                abort("Source should not be absolute: '{}' in '{}'".format(source_path, destination), context=self)
            _install_source_files(((source_file, _arcname_f(source_file)) for source_file in glob.iglob(file_path)), include=source_path, excludes=source.get('exclude'))
        elif source_type == 'link':
            link_target = source['path']
            if destination.endswith('/'):
                link_target_basename = basename(link_target)
                absolute_destination = join(absolute_destination, link_target_basename)
                clean_destination = join(clean_destination, link_target_basename)
            add_symlink(destination, link_target, absolute_destination, clean_destination)
        elif source_type == 'string':
            if destination.endswith('/'):
                abort("Can not use `string` source with a destination ending with `/` ({})".format(destination), context=self)
            ensure_dir_exists(dirname(absolute_destination))
            s = source['value']
            with open(absolute_destination, 'w') as f:
                f.write(s)
            archiver.add_str(s, clean_destination, provenance)
        elif source_type == 'skip':
            pass
        else:
            abort("Unsupported source type: '{}' in '{}'".format(source_type, destination), context=self)

    def _verify_layout(self):
        output = realpath(self.get_output())
        for destination, sources in self.layout.items():
            if not isinstance(destination, str):
                abort("Destination (layout keys) should be a string", context=self)
            if not isinstance(sources, list):
                sources = [sources]
            if not destination:
                abort("Destination (layout keys) can not be empty", context=self)
            for source in sources:
                if not isinstance(source, (str, dict)):
                    abort("Error in '{}': sources should be strings or dicts".format(destination), context=self)
            if isabs(destination):
                abort("Invalid destination: '{}': destination should not be absolute".format(destination), context=self)
            final_destination = normpath(join(output, destination))
            if not final_destination.startswith(output):
                abort("Invalid destination: '{}': destination should not escape the output directory ('{}' is not in '{}')".format(destination, final_destination, output), context=self)
            if not destination.endswith('/'):
                if len(sources) > 1:
                    abort("Invalid layout: cannot copy multiple files to a single destination: '{dest}'\n"
                          "Should the destination be a directory: '{dest}/'? (note the trailing slash)".format(dest=destination), context=self)
                if len(sources) < 1:
                    abort("Invalid layout: no file to copy to '{dest}'\n"
                          "Do you want an empty directory: '{dest}/'? (note the trailing slash)".format(dest=destination), context=self)

    def make_archive(self):
        self._verify_layout()
        output = realpath(self.get_output())
        with self.archive_factory(self.path,
                                  kind=self.localExtension(),
                                  duplicates_action='warn',
                                  context=self,
                                  reset_user_group=getattr(self, 'reset_user_group', False),
                                  compress=self.compress) as arc:
            for destination, source in self._walk_layout():
                self._install_source(source, output, destination, arc)
        self._persist_layout()
        self._persist_linky_state()

    def needsUpdate(self, newestInput):
        sup = super(LayoutDistribution, self).needsUpdate(newestInput)
        if sup:
            return sup
        for destination, source in self._walk_layout():
            source_type = source['source_type']
            if source_type == 'file':
                for source_file in glob.iglob(join(self.suite.dir, source['path'])):
                    up = _needsUpdate(source_file, self.path)
                    if up:
                        return up
                    if islink(source_file):
                        source_file = join(dirname(source_file), os.readlink(source_file))
                        up = _needsUpdate(source_file, self.path)
                        if up:
                            return up
                    elif isdir(source_file):
                        for root, _, files in os.walk(source_file):
                            up = _needsUpdate(root, self.path)
                            if up:
                                return up
                            for f in files:
                                up = _needsUpdate(join(root, f), self.path)
                                if up:
                                    return up
            elif source_type == 'link':
                pass  # this is handled by _persist_layout
            elif source_type == 'string':
                pass  # this is handled by _persist_layout
            elif source_type in ('dependency', 'extracted-dependency', 'skip'):
                pass  # this is handled by a build task dependency
            else:
                abort("Unsupported source type: '{}' in '{}'".format(source_type, destination), context=suite)
        if not self._check_persisted_layout():
            return "layout definition has changed"
        if not self._check_linky_state():
            return "LINKY_LAYOUT has changed"
        return None

    def _persist_layout(self):
        saved_layout_file = self._persisted_layout_file()
        current_layout = LayoutDistribution._layout_to_stable_str(self.layout)
        ensure_dir_exists(dirname(saved_layout_file))
        with open(saved_layout_file, 'w') as fp:
            fp.write(current_layout)

    def _persisted_layout_file(self):
        return join(self.suite.get_mx_output_dir(), 'savedLayouts', self.name)

    @staticmethod
    def _layout_to_stable_str(d):
        if isinstance(d, list):
            return '[' + ','.join((LayoutDistribution._layout_to_stable_str(e) for e in d)) + ']'
        elif isinstance(d, dict):
            return '{' + ','.join(("{}->{}".format(k, LayoutDistribution._layout_to_stable_str(d[k])) for k in sorted(d.keys()))) + '}'
        else:
            return '{}'.format(d)

    def _check_persisted_layout(self):
        saved_layout_file = self._persisted_layout_file()
        current_layout = LayoutDistribution._layout_to_stable_str(self.layout)
        saved_layout = ""
        if exists(saved_layout_file):
            with open(saved_layout_file) as fp:
                saved_layout = fp.read()

        if saved_layout == current_layout:
            return True
        logv("'{}'!='{}'".format(saved_layout, current_layout))
        return False

    def _linky_state_file(self):
        return join(self.suite.get_mx_output_dir(), 'linkyState', self.name)

    def _persist_linky_state(self):
        linky_state_file = self._linky_state_file()
        LayoutDistribution._is_linky()  # force init
        if LayoutDistribution._linky is None:
            if exists(linky_state_file):
                os.unlink(linky_state_file)
            return
        ensure_dir_exists(dirname(linky_state_file))
        with open(linky_state_file, 'w') as fp:
            fp.write(LayoutDistribution._linky.pattern)

    def _check_linky_state(self):
        linky_state_file = self._linky_state_file()
        LayoutDistribution._is_linky()  # force init
        if not exists(linky_state_file):
            return LayoutDistribution._linky is None
        if LayoutDistribution._linky is None:
            return False
        with open(linky_state_file) as fp:
            saved_pattern = fp.read()
        return saved_pattern == LayoutDistribution._linky.pattern

    def find_single_source_location(self, source, fatal_if_missing=True, abort_on_multiple=False):
        locations = self.find_source_location(source, fatal_if_missing=fatal_if_missing)
        if len(locations) > 1:
            abort_or_warn("Found multiple locations for '{}' in '{}': {}".format(source, self.name, locations), abort_on_multiple)
        if len(locations) > 0:
            return locations[0]
        return None

    def find_source_location(self, source, fatal_if_missing=True):
        if source not in self._source_location_cache:
            source_dict = LayoutDistribution._as_source_dict(source, self.name, "??", self.path_substitutions, self.string_substitutions, self, self)
            source_type = source_dict['source_type']
            if source_type in ('dependency', 'extracted-dependency', 'skip'):
                dep = source_dict['dependency']
                if source_dict['path'] is None:
                    found_dest = []
                    for destination, layout_source in self._walk_layout():
                        if layout_source['source_type'] == source_type and layout_source['path'] is None and layout_source['dependency'] == dep:
                            dest = destination
                            if dest.startswith('./'):
                                dest = dest[2:]
                            if source_type == 'dependency' and destination.endswith('/'):
                                d = dependency(source_dict['dependency'], context=self)
                                _, arcname = next(d.getArchivableResults(single=True))
                                dest = join(dest, basename(arcname))
                            found_dest.append(dest)
                    self._source_location_cache[source] = found_dest
                    if fatal_if_missing and not found_dest:
                        abort("Could not find '{}' in '{}'".format(source, self.name))
                else:
                    abort("find_source_location: path is not supported: " + source)
            else:
                abort("find_source_location: source type not supported: " + source)
        return self._source_location_cache[source]


class LayoutTARDistribution(LayoutDistribution, AbstractTARDistribution): #pylint: disable=too-many-ancestors
    pass


class LayoutJARDistribution(LayoutDistribution, AbstractJARDistribution): #pylint: disable=too-many-ancestors
    def __init__(self, *args, **kw_args):
        # we have *args here because some subclasses in suites have been written passing positional args to
        # LayoutDistribution.__init__ instead of keyword args. We just forward it as-is to super(), it's risky but better
        # than breaking compatibility with the mis-behaving suites
        self._local_compress = kw_args.pop('localCompress', False)
        self._remote_compress = kw_args.pop('remoteCompress', True)
        if self._local_compress and not self._remote_compress:
            abort("Incompatible local/remote compression settings: local compression requires remote compression")
        super(LayoutJARDistribution, self).__init__(*args, compress=self._local_compress, **kw_args)

    def compress_locally(self):
        return self._local_compress

    def compress_remotely(self):
        return self._remote_compress


### ~~~~~~~~~~~~~ Project, Dependency
class Project(Dependency):
    __metaclass__ = ABCMeta
    """
    A Project is a collection of source code that is built by mx. For historical reasons
    it typically corresponds to an IDE project and the IDE support in mx assumes this.
    """
    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense, testProject=False, **kwArgs):
        """
        :param list[str] srcDirs: subdirectories of name containing sources to build
        :param list[str] | list[Dependency] deps: list of dependencies, Project, Library or Distribution
        """
        Dependency.__init__(self, suite, name, theLicense, **kwArgs)
        self.subDir = subDir
        self.srcDirs = srcDirs
        self.deps = deps
        self.workingSets = workingSets
        self.dir = d
        self.testProject = testProject
        if self.testProject is None:
            # The suite doesn't specify whether this is a test suite.  By default,
            # any project ending with .test is considered a test project.  Prior
            # to mx version 5.114.0, projects ending in .jtt are also treated this
            # way but starting with the version any non-standard names must be
            # explicitly marked as test projects.
            self.testProject = self.name.endswith('.test')
            if not self.testProject and not self.suite.getMxCompatibility().disableImportOfTestProjects():
                self.testProject = self.name.endswith('.jtt')

        # Create directories for projects that don't yet exist
        ensure_dir_exists(d)
        for s in self.source_dirs():
            ensure_dir_exists(s)

    def resolveDeps(self):
        """
        Resolves symbolic dependency references to be Dependency objects.
        """
        self._resolveDepsHelper(self.deps)
        licenseId = self.theLicense if self.theLicense else self.suite.defaultLicense
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)
        if hasattr(self, 'buildDependencies'):
            self._resolveDepsHelper(self.buildDependencies)

    def get_output_root(self):
        """
        Gets the root of the directory hierarchy under which generated artifacts for this
        project such as class files and annotation generated sources should be placed.
        """
        if not self.subDir:
            return join(self.get_output_base(), self.name)
        names = self.subDir.split(os.sep)
        parents = len([n for n in names if n == os.pardir])
        if parents != 0:
            return os.sep.join([self.get_output_base(), '{}-parent-{}'.format(self.suite, parents)] + names[parents:] + [self.name])
        return join(self.get_output_base(), self.subDir, self.name)

    def _walk_deps_visit_edges(self, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        deps = [(DEP_STANDARD, self.deps)]
        if hasattr(self, 'buildDependencies'):
            deps.append((DEP_BUILD, self.buildDependencies))
        self._walk_deps_visit_edges_helper(deps, visited, in_edge, preVisit=preVisit, visit=visit, ignoredEdges=ignoredEdges, visitEdge=visitEdge)

    def _compute_max_dep_distances(self, dep, distances, dist):
        currentDist = distances.get(dep)
        if currentDist is None or currentDist < dist:
            distances[dep] = dist
            if dep.isProject():
                for depDep in dep.deps:
                    self._compute_max_dep_distances(depDep, distances, dist + 1)

    def canonical_deps(self):
        """
        Get the dependencies of this project that are not recursive (i.e. cannot be reached
        via other dependencies).
        """
        distances = dict()
        result = set()
        self._compute_max_dep_distances(self, distances, 0)
        for n, d in distances.items():
            assert d > 0 or n is self
            if d == 1:
                result.add(n)

        if len(result) == len(self.deps) and frozenset(self.deps) == result:
            return self.deps
        return result

    def max_depth(self):
        """
        Get the maximum canonical distance between this project and its most distant dependency.
        """
        distances = dict()
        self._compute_max_dep_distances(self.name, distances, 0)
        return max(distances.values())

    def source_dirs(self):
        """
        Get the directories in which the sources of this project are found.
        """
        return [join(self.dir, s) for s in self.srcDirs]

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        nyi('eclipse_settings_sources', self)

    def netbeans_settings_sources(self):
        """
        Gets a dictionary from the name of an NetBeans settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        nyi('netbeans_settings_sources', self)

    def eclipse_config_up_to_date(self, configZip):
        """
        Determines if the zipped up Eclipse configuration
        """
        return True

    def netbeans_config_up_to_date(self, configZip):
        """
        Determines if the zipped up NetBeans configuration
        """
        return True

    def get_javac_lint_overrides(self):
        """
        Gets a string to be added to the -Xlint javac option.
        """
        nyi('get_javac_lint_overrides', self)

    def _eclipseinit(self, files=None, libFiles=None, absolutePaths=False):
        """
        Generates an Eclipse project configuration for this project if Eclipse
        supports projects of this type.
        """

    def is_test_project(self):
        return self.testProject

    def get_checkstyle_config(self, resolve_checkstyle_library=True):
        # Workaround for GR-12809
        return (None, None, None)

class ProjectBuildTask(BuildTask):
    __metaclass__ = ABCMeta

    def __init__(self, args, parallelism, project):
        BuildTask.__init__(self, project, args, parallelism)


class ArchivableProject(Project):  # Used from other suites. pylint: disable=r0921
    """
    A project that can be part of any distribution, native or not.
    Users should subclass this class and implement the nyi() methods.
    The files listed by getResults(), which must be under output_dir(),
    will be included in the archive under the prefix archive_prefix().
    """
    __metaclass__ = ABCMeta
    def __init__(self, suite, name, deps, workingSets, theLicense, **kwArgs):
        d = suite.dir
        Project.__init__(self, suite, name, "", [], deps, workingSets, d, theLicense, **kwArgs)

    def getBuildTask(self, args):
        return ArchivableBuildTask(self, args, 1)

    @abstractmethod
    def output_dir(self):
        nyi('output_dir', self)

    @abstractmethod
    def archive_prefix(self):
        nyi('archive_prefix', self)

    @abstractmethod
    def getResults(self):
        nyi('getResults', self)

    @staticmethod
    def walk(d):
        """
        Convenience method to implement getResults() by including all files under a directory.
        """
        assert isabs(d)
        results = []
        for root, _, files in os.walk(d):
            for name in files:
                path = join(root, name)
                results.append(path)
        return results

    def get_relpath(self, f, outputDir):
        d = join(outputDir, "")
        assert f.startswith(d), f + " not in " + outputDir
        return os.path.relpath(f, outputDir)

    def getArchivableResults(self, use_relpath=True, single=False):
        if single:
            raise ValueError("single not supported")
        outputDir = self.output_dir()
        archivePrefix = self.archive_prefix()
        for f in self.getResults():
            if use_relpath:
                filename = self.get_relpath(f, outputDir)
            else:
                filename = basename(f)
            arcname = join(archivePrefix, filename)
            yield f, arcname

class ArchivableBuildTask(BuildTask):
    def __str__(self):
        return 'Archive {}'.format(self.subject)

    def needsBuild(self, newestInput):
        return (False, 'Files are already on disk')

    def newestOutput(self):
        return TimeStampFile.newest(self.subject.getResults())

    def build(self):
        pass

    def clean(self, forBuild=False):
        pass

#### ~~~~~~~~~~~~~ Project: Java / Maven

class MavenProject(Project, ClasspathDependency):
    """
    A project producing a single jar file.
    Users should subclass this class and implement getBuildTask().
    Additional attributes:
      jar: path to the jar
      sourceDirs: list of directories containing the sources
    """
    def __init__(self, suite, name, deps, workingSets, theLicense=None, **args):
        context = 'project ' + name
        d = suite.dir
        srcDirs = Suite._pop_list(args, 'sourceDirs', context)
        Project.__init__(self, suite, name, "", srcDirs, deps, workingSets, d, theLicense, **args)
        ClasspathDependency.__init__(self)
        jar = args.pop('jar')
        assert jar.endswith('.jar')
        self.jar = jar

    def classpath_repr(self, resolve=True):
        jar = join(self.suite.dir, self.jar)
        if resolve and not exists(jar):
            abort('unbuilt Maven project {} cannot be on a class path ({})'.format(self, jar))
        return jar

    def get_path(self, resolve):
        return self.classpath_repr(resolve=resolve)

    def get_source_path(self, resolve):
        assert len(self.sourceDirs) == 1
        return join(self.suite.dir, self.sourceDirs[0])

class JavaProject(Project, ClasspathDependency):
    def __init__(self, suite, name, subDir, srcDirs, deps, javaCompliance, workingSets, d, theLicense=None, testProject=False, **kwArgs):
        Project.__init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense, testProject=testProject, **kwArgs)
        ClasspathDependency.__init__(self, **kwArgs)
        if javaCompliance is None:
            abort('javaCompliance property required for Java project ' + name)
        self.javaCompliance = JavaCompliance(javaCompliance)
        # The annotation processors defined by this project
        self.definedAnnotationProcessors = None
        self.declaredAnnotationProcessors = []
        self._mismatched_imports = None
        self._overlays = []

    @property
    def include_dirs(self):
        """Directories with headers provided by this project."""
        return [self.jni_gen_dir()] if self.jni_gen_dir() else []

    def resolveDeps(self):
        Project.resolveDeps(self)
        self._resolveDepsHelper(self.declaredAnnotationProcessors)
        for ap in self.declaredAnnotationProcessors:
            if not ap.isDistribution() and not ap.isLibrary():
                abort('annotation processor dependency must be a distribution or a library: ' + ap.name, context=self)

        if self.suite.getMxCompatibility().disableImportOfTestProjects() and not self.is_test_project():
            for dep in self.deps:
                if isinstance(dep, Project) and dep.is_test_project():
                    abort('Non-test project {} can not depend on the test project {}'.format(self.name, dep.name))
        overlayTargetName = getattr(self, 'overlayTarget', None)
        if hasattr(self, 'multiReleaseJarVersion'):
            if self.suite.getMxCompatibility().automatic_overlay_distribution_deps() and overlayTargetName is None:
                abort('Project with "multiReleaseJarVersion" attribute must also have an "overlayTarget" attribute', context=self)
        if overlayTargetName:
            project(self.overlayTarget, context=self)._overlays.append(self)

    def _walk_deps_visit_edges(self, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        deps = [(DEP_ANNOTATION_PROCESSOR, self.declaredAnnotationProcessors)]
        self._walk_deps_visit_edges_helper(deps, visited, in_edge, preVisit, visit, ignoredEdges, visitEdge)
        Project._walk_deps_visit_edges(self, visited, in_edge, preVisit, visit, ignoredEdges, visitEdge)

    def source_gen_dir_name(self):
        """
        Get the directory name in which source files generated by the annotation processor are found/placed.
        """
        return basename(self.source_gen_dir())

    def source_gen_dir(self, relative=False):
        """
        Get the absolute path to the directory in which source files generated by the annotation processor are found/placed.
        """
        res = join(self.get_output_root(), 'src_gen')
        if relative:
            res = os.path.relpath(res, self.dir)
        return res

    def jni_gen_dir(self, relative=False):
        if getattr(self, 'jniHeaders', False):
            res = join(self.get_output_root(), 'jni_gen')
            if relative:
                res = os.path.relpath(res, self.dir)
            return res
        return None

    def output_dir(self, relative=False):
        """
        Get the directory in which the class files of this project are found/placed.
        """
        res = join(self.get_output_root(), 'bin')
        if relative:
            res = os.path.relpath(res, self.dir)
        return res

    def classpath_repr(self, resolve=True):
        return self.output_dir()

    def get_javac_lint_overrides(self):
        if not hasattr(self, '_javac_lint_overrides'):
            overrides = []
            if get_env('JAVAC_LINT_OVERRIDES'):
                overrides += get_env('JAVAC_LINT_OVERRIDES').split(',')
            if self.suite.javacLintOverrides:
                overrides += self.suite.javacLintOverrides
            if hasattr(self, 'javac.lint.overrides'):
                overrides += getattr(self, 'javac.lint.overrides').split(',')
            self._javac_lint_overrides = overrides
        return self._javac_lint_overrides

    def eclipse_config_up_to_date(self, configZip):
        for _, sources in self.eclipse_settings_sources().items():
            for source in sources:
                if configZip.isOlderThan(source):
                    return False
        return True

    def netbeans_config_up_to_date(self, configZip):
        for _, sources in self.netbeans_settings_sources().items():
            for source in sources:
                if configZip.isOlderThan(source):
                    return False

        if configZip.isOlderThan(join(self.dir, 'build.xml')):
            return False

        if configZip.isOlderThan(join(self.dir, 'nbproject', 'project.xml')):
            return False

        if configZip.isOlderThan(join(self.dir, 'nbproject', 'project.properties')):
            return False

        return True

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        esdict = self.suite.eclipse_settings_sources()

        # check for project overrides
        projectSettingsDir = join(self.dir, 'eclipse-settings')
        if exists(projectSettingsDir):
            for name in os.listdir(projectSettingsDir):
                esdict.setdefault(name, []).append(os.path.abspath(join(projectSettingsDir, name)))

        if not self.annotation_processors():
            esdict.pop("org.eclipse.jdt.apt.core.prefs", None)

        return esdict

    def netbeans_settings_sources(self):
        """
        Gets a dictionary from the name of an NetBeans settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        nbdict = self.suite.netbeans_settings_sources()

        # check for project overrides
        projectSettingsDir = join(self.dir, 'netbeans-settings')
        if exists(projectSettingsDir):
            for name in os.listdir(projectSettingsDir):
                nbdict.setdefault(name, []).append(os.path.abspath(join(projectSettingsDir, name)))

        return nbdict

    def get_checkstyle_config(self, resolve_checkstyle_library=True):
        """
        Gets a tuple of the path to a Checkstyle configuration file, a Checkstyle version
        and the project supplying the Checkstyle configuration file. Returns
        (None, None, None) if this project has no Checkstyle configuration.
        """
        checkstyleProj = self if self.checkstyleProj == self.name else project(self.checkstyleProj, context=self)
        config = join(checkstyleProj.dir, '.checkstyle_checks.xml')
        if not exists(config):
            compat = self.suite.getMxCompatibility()
            should_abort = compat.check_checkstyle_config()
            if checkstyleProj != self:
                abort_or_warn('Project {} has no Checkstyle configuration'.format(checkstyleProj), should_abort, context=self)
            else:
                if hasattr(self, 'checkstyleVersion'):
                    abort_or_warn('Cannot specify "checkstyleVersion" attribute for project with non-existent Checkstyle configuration', should_abort, context=self)
            return None, None, None

        if hasattr(checkstyleProj, 'checkstyleVersion'):
            checkstyleVersion = checkstyleProj.checkstyleVersion
            if resolve_checkstyle_library:
                library('CHECKSTYLE_' + checkstyleVersion, context=checkstyleProj)
        else:
            checkstyleVersion = checkstyleProj.suite.getMxCompatibility().checkstyleVersion()
        return config, checkstyleVersion, checkstyleProj

    def find_classes_with_annotations(self, pkgRoot, annotations, includeInnerClasses=False, includeGenSrc=False):
        """
        Scan the sources of this project for Java source files containing a line starting with 'annotation'
        (ignoring preceding whitespace) and return a dict mapping fully qualified class names to a tuple
        consisting of the source file and line number of a match.
        """

        matches = lambda line: len([a for a in annotations if line == a or line.startswith(a + '(')]) != 0
        return self.find_classes_with_matching_source_line(pkgRoot, matches, includeInnerClasses, includeGenSrc)

    def find_classes_with_matching_source_line(self, pkgRoot, function, includeInnerClasses=False, includeGenSrc=False):
        """
        Scan the sources of this project for Java source files containing a line for which
        'function' returns true. A map from class name to source file path for each existing class
        corresponding to a matched source file is returned.
        """
        result = dict()
        source_dirs = self.source_dirs()
        if includeGenSrc:
            source_dirs.append(self.source_gen_dir())

        for srcDir in source_dirs:
            outputDir = self.output_dir()
            for root, _, files in os.walk(srcDir):
                for name in files:
                    if name.endswith('.java') and name != 'package-info.java':
                        matchingLineFound = None
                        source = join(root, name)
                        with open(source) as f:
                            pkg = None
                            lineNo = 1
                            for line in f:
                                if line.startswith("package "):
                                    match = _java_package_regex.match(line)
                                    if match:
                                        pkg = match.group(1)
                                if function(line.strip()):
                                    matchingLineFound = lineNo
                                if pkg and matchingLineFound:
                                    break
                                lineNo += 1

                        if matchingLineFound:
                            simpleClassName = name[:-len('.java')]
                            assert pkg is not None, 'could not find package statement in file ' + name
                            className = pkg + '.' + simpleClassName
                            result[className] = (source, matchingLineFound)
                            if includeInnerClasses:
                                if pkgRoot is None or pkg.startswith(pkgRoot):
                                    pkgOutputDir = join(outputDir, pkg.replace('.', os.path.sep))
                                    if exists(pkgOutputDir):
                                        for e in os.listdir(pkgOutputDir):
                                            if e.endswith('.class') and e.startswith(simpleClassName + '$'):
                                                className = pkg + '.' + e[:-len('.class')]
                                                result[className] = (source, matchingLineFound)
        return result

    def _init_packages_and_imports(self):
        if not hasattr(self, '_defined_java_packages'):
            packages = set()
            extendedPackages = set()
            depPackages = set()
            def visit(dep, edge):
                if dep is not self and dep.isProject():
                    depPackages.update(dep.defined_java_packages())
            self.walk_deps(visit=visit)
            imports = set()
            mismatched_imports = {}
            # Assumes package name components start with lower case letter and
            # classes start with upper-case letter
            importStatementRe = re.compile(r'\s*import\s+(?:static\s+)?([a-zA-Z\d_$\.]+\*?)\s*;\s*')
            importedRe = re.compile(r'((?:[a-z][a-zA-Z\d_$]*\.)*[a-z][a-zA-Z\d_$]*)\.(?:(?:[A-Z][a-zA-Z\d_$]*)|\*)')
            for sourceDir in self.source_dirs():
                for root, _, files in os.walk(sourceDir):
                    javaSources = [name for name in files if name.endswith('.java')]
                    if len(javaSources) != 0:
                        path_package = root[len(sourceDir) + 1:].replace(os.sep, '.')
                        if path_package not in depPackages:
                            packages.add(path_package)
                        else:
                            # A project extends a package already defined by one of it dependencies
                            extendedPackages.add(path_package)
                            imports.add(path_package)

                        for n in javaSources:
                            java_package = None
                            java_source = join(root, n)
                            with open(java_source) as fp:
                                for i, line in enumerate(fp):
                                    m = importStatementRe.match(line)
                                    if m:
                                        imported = m.group(1)
                                        m = importedRe.match(imported)
                                        if not m:
                                            lineNo = i + 1
                                            abort(java_source + ':' + str(lineNo) + ': import statement does not match expected pattern:\n' + line, self)
                                        package = m.group(1)
                                        imports.add(package)
                                    m = _java_package_regex.match(line)
                                    if m:
                                        java_package = m.group('package')
                            if java_package != path_package:
                                mismatched_imports[java_source] = java_package

            self._defined_java_packages = frozenset(packages)
            self._extended_java_packages = frozenset(extendedPackages)
            self._mismatched_imports = mismatched_imports

            importedPackagesFromProjects = set()
            compat = self.suite.getMxCompatibility()
            for package in imports:
                if compat.improvedImportMatching():
                    if package in depPackages:
                        importedPackagesFromProjects.add(package)
                else:
                    name = package
                    while not name in depPackages and len(name) > 0:
                        lastDot = name.rfind('.')
                        if lastDot == -1:
                            name = None
                            break
                        name = name[0:lastDot]
                    if name is not None:
                        importedPackagesFromProjects.add(name)

            setattr(self, '.importedPackages', frozenset(imports))
            setattr(self, '.importedPackagesFromJavaProjects', frozenset(importedPackagesFromProjects))

    def defined_java_packages(self):
        """Get the immutable set of Java packages defined by the Java sources of this project"""
        self._init_packages_and_imports()
        return self._defined_java_packages

    def extended_java_packages(self):
        """Get the immutable set of Java packages extended by the Java sources of this project"""
        self._init_packages_and_imports()
        return self._extended_java_packages

    def imported_java_packages(self, projectDepsOnly=True):
        """
        Gets the immutable set of Java packages imported by the Java sources of this project.

        :param bool projectDepsOnly: only include packages defined by other Java projects in the result
        :return: the packages imported by this Java project, filtered as per `projectDepsOnly`
        :rtype: frozenset
        """
        self._init_packages_and_imports()
        return getattr(self, '.importedPackagesFromJavaProjects') if projectDepsOnly else getattr(self, '.importedPackages')

    def mismatched_imports(self):
        """Get a dictionary of source files whose package declaration does not match their source location"""
        self._init_packages_and_imports()
        return self._mismatched_imports

    def annotation_processors(self):
        """
        Gets the list of dependencies defining the annotation processors that will be applied
        when compiling this project.
        """
        return self.declaredAnnotationProcessors

    def annotation_processors_path(self, jdk):
        """
        Gets the class path composed of this project's annotation processor jars and the jars they depend upon.
        """
        aps = self.annotation_processors()
        if len(aps):
            entries = classpath_entries(names=aps)
            invalid = [e.classpath_repr(resolve=True) for e in entries if not e.isJar()]
            if invalid:
                abort('Annotation processor path can only contain jars: ' + str(invalid), context=self)
            entries = (e.classpath_repr(jdk, resolve=True) if e.isJdkLibrary() else e.classpath_repr(resolve=True) for e in entries)
            return os.pathsep.join((e for e in entries if e))
        return None

    def check_current_annotation_processors_file(self):
        aps = self.annotation_processors()
        outOfDate = False
        currentApsFile = join(self.suite.get_mx_output_dir(), 'currentAnnotationProcessors', self.name)
        currentApsFileExists = exists(currentApsFile)
        if currentApsFileExists:
            with open(currentApsFile) as fp:
                currentAps = [l.strip() for l in fp.readlines()]
            if currentAps != [ap.name for ap in aps]:
                outOfDate = True
            elif len(aps) == 0:
                os.remove(currentApsFile)
        else:
            outOfDate = len(aps) != 0
        return outOfDate

    def update_current_annotation_processors_file(self):
        aps = self.annotation_processors()
        currentApsFile = join(self.suite.get_mx_output_dir(), 'currentAnnotationProcessors', self.name)
        if len(aps) != 0:
            ensure_dir_exists(dirname(currentApsFile))
            with open(currentApsFile, 'w') as fp:
                for ap in aps:
                    print(ap, file=fp)
        else:
            if exists(currentApsFile):
                os.remove(currentApsFile)

    def make_archive(self, path=None):
        outputDir = self.output_dir()
        if not path:
            path = join(self.get_output_root(), self.name + '.jar')
        with Archiver(path) as arc:
            for root, _, files in os.walk(outputDir):
                for f in files:
                    relpath = root[len(outputDir) + 1:]
                    arcname = join(relpath, f).replace(os.sep, '/')
                    arc.zf.write(join(root, f), arcname)
        return path

    def _eclipseinit(self, files=None, libFiles=None, absolutePaths=False):
        """
        Generates an Eclipse project configuration for this project.
        """
        _eclipseinit_project(self, files=files, libFiles=libFiles, absolutePaths=absolutePaths)

    def get_overlay_flatten_map(self):
        """
        Gets a map from the source directories of this project to the
        source directories the project it overlays (or
        [presides overs](https://docs.oracle.com/javase/9/docs/specs/jar/jar.html)).

        :return: an empty map if this is not an overlay or multi-release version project
        """
        if hasattr(self, 'overlayTarget'):
            base = project(self.overlayTarget, context=self)
        elif hasattr(self, 'multiReleaseJarVersion'):
            def _find_version_base_project():
                extended_packages = self.extended_java_packages()
                if not extended_packages:
                    abort('Project with a multiReleaseJarVersion attribute must depend on a project that defines a package extended by ' + self.name, context=self)
                base_project = None
                base_package = None
                for extended_package in extended_packages:
                    for dep in classpath_entries(self, includeSelf=False, preferProjects=True):
                        if dep is not self and dep.isJavaProject() and not hasattr(dep, 'multiReleaseJarVersion'):
                            if extended_package in dep.defined_java_packages():
                                if base_project is None:
                                    base_project = dep
                                    base_package = extended_package
                                else:
                                    if base_project != dep:
                                        abort('Multi-release jar versioned project {} must extend packages from exactly one project but extends {} from {} and {} from {}'.format(self, extended_package, dep, base_project, base_package))
                if not base_project:
                    abort('Multi-release jar versioned project {} must extend package(s) from one of its dependencies'.format(self))
                return base_project
            base = _find_version_base_project()
        else:
            return {}

        flatten_map = {}
        self_packages = self.defined_java_packages() | self.extended_java_packages()
        for package in self_packages:
            relative_package_src_dir = package.replace('.', os.sep)
            for self_package_src_dir in [join(s, relative_package_src_dir) for s in self.source_dirs()]:
                if exists(self_package_src_dir):
                    assert len(base.source_dirs()) != 0, '{} has no source directories!'.format(base)
                    for base_package_src_dir in [join(s, relative_package_src_dir) for s in base.source_dirs()]:
                        if exists(base_package_src_dir) or self_package_src_dir not in flatten_map:
                            flatten_map[self_package_src_dir] = base_package_src_dir
        assert len(self_packages) == len(flatten_map), 'could not find sources for all packages in ' + self.name
        return flatten_map

    def getBuildTask(self, args):
        jdk = get_jdk(self.javaCompliance, tag=DEFAULT_JDK_TAG, purpose='building ' + self.name)
        return JavaBuildTask(args, self, jdk)

    def get_concealed_imported_packages(self, jdk=None, modulepath=None):
        """
        Gets the concealed packages imported by this Java project and its transitive project dependencies.

        :param JDKConfig jdk: the JDK whose modules are to be searched for concealed packages
        :param list modulepath: extra modules to be searched for concealed packages
        :return: a map from a module to its concealed packages imported by this project
        """
        if jdk is None:
            jdk = get_jdk(self.javaCompliance)
        if modulepath is None:
            modulepath = []
        else:
            assert isinstance(modulepath, list)
        cache = '.concealed_imported_packages@' + str(jdk.version) + '@' + ':'.join([m.name for m in modulepath])
        if getattr(self, cache, None) is None:
            concealed = {}
            if jdk.javaCompliance >= '9':
                modulepath = list(jdk.get_modules()) + modulepath
                def visit(dep, edge):
                    if dep is not self and dep.isJavaProject():
                        dep_concealed = dep.get_concealed_imported_packages(jdk=jdk, modulepath=modulepath)
                        for module, packages in dep_concealed.items():
                            concealed.setdefault(module, set()).update(packages)
                self.walk_deps(visit=visit)

                imports = getattr(self, 'imports', [])
                if imports:
                    # This regex does not detect all legal packages names. No regex can tell you if a.b.C.D is
                    # a class D in the package a.b.C, a class C.D in the package a.b or even a class b.C.D in
                    # the package a. As such mx uses the convention that package names start with a lowercase
                    # letter and class names with a uppercase letter.
                    packageRe = re.compile(r'(?:[a-z][a-zA-Z\d_$]*\.)*[a-z][a-zA-Z\d_$]*$')
                    for imported in imports:
                        m = packageRe.match(imported)
                        if not m:
                            abort('"imports" contains an entry that does not match expected pattern for package name: ' + imported, self)
                imported = itertools.chain(imports, self.imported_java_packages(projectDepsOnly=False))
                for package in imported:
                    jmd, visibility = lookup_package(modulepath, package, "<unnamed>")
                    if visibility == 'concealed':
                        if self.defined_java_packages().isdisjoint(jmd.packages):
                            concealed.setdefault(jmd.name, set()).add(package)
                        else:
                            # This project is part of the module defining the concealed package
                            pass
            concealed = {module : list(concealed[module]) for module in concealed}
            setattr(self, cache, concealed)
        return getattr(self, cache)

### ~~~~~~~~~~~~~ Build task

class JavaBuildTask(ProjectBuildTask):
    def __init__(self, args, project, jdk):
        ProjectBuildTask.__init__(self, args, 1, project)
        self.jdk = jdk
        self.javafilelist = None
        self.nonjavafiletuples = None
        self.nonjavafilecount = None
        self._newestOutput = None
        self._compiler = None

    def __str__(self):
        return "Compiling {} with {}".format(self.subject.name, self._getCompiler().name())

    def initSharedMemoryState(self):
        ProjectBuildTask.initSharedMemoryState(self)
        self._newestBox = multiprocessing.Array('c', 2048)

    def pushSharedMemoryState(self):
        ProjectBuildTask.pushSharedMemoryState(self)
        self._newestBox.value = _encode(self._newestOutput.path if self._newestOutput else '')

    def pullSharedMemoryState(self):
        ProjectBuildTask.pullSharedMemoryState(self)
        self._newestOutput = TimeStampFile(_decode(self._newestBox.value)) if self._newestBox.value else None

    def cleanSharedMemoryState(self):
        ProjectBuildTask.cleanSharedMemoryState(self)
        self._newestBox = None

    def buildForbidden(self):
        if ProjectBuildTask.buildForbidden(self):
            return True
        if not self.args.java:
            return True
        if exists(join(self.subject.dir, 'plugin.xml')):  # eclipse plugin project
            return True
        return False

    def cleanForbidden(self):
        if ProjectBuildTask.cleanForbidden(self):
            return True
        if not self.args.java:
            return True
        return False

    def needsBuild(self, newestInput):
        sup = ProjectBuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        reason = self._collectFiles(checkBuildReason=True, newestInput=newestInput)
        if reason:
            return (True, reason)

        if self.subject.check_current_annotation_processors_file():
            return (True, 'annotation processor(s) changed')

        if len(self._javaFileList()) == 0 and self._nonJavaFileCount() == 0:
            return (False, 'no sources')
        return (False, 'all files are up to date')

    def newestOutput(self):
        return self._newestOutput

    def _javaFileList(self):
        if not self.javafilelist:
            self._collectFiles()
        return self.javafilelist

    def _nonJavaFileTuples(self):
        if not self.nonjavafiletuples:
            self._collectFiles()
        return self.nonjavafiletuples

    def _nonJavaFileCount(self):
        if self.nonjavafiletuples is None:
            self._collectFiles()
        return self.nonjavafiletuples

    def _collectFiles(self, checkBuildReason=False, newestInput=None):
        self.javafilelist = []
        self.nonjavafiletuples = []
        self.nonjavafilecount = 0
        buildReason = None
        outputDir = self.subject.output_dir()
        for sourceDir in self.subject.source_dirs():
            for root, _, files in os.walk(sourceDir, followlinks=True):
                javafiles = [join(root, name) for name in files if name.endswith('.java')]
                self.javafilelist += javafiles
                nonjavafiles = [join(root, name) for name in files if not name.endswith('.java')]
                self.nonjavafiletuples += [(sourceDir, nonjavafiles)]
                self.nonjavafilecount += len(nonjavafiles)

                def findBuildReason():
                    for inputs, inputSuffix, outputSuffix in [(javafiles, 'java', 'class'), (nonjavafiles, None, None)]:
                        for inputFile in inputs:
                            if basename(inputFile) == 'package-info.java':
                                continue
                            if inputSuffix:
                                witness = TimeStampFile(outputDir + inputFile[len(sourceDir):-len(inputSuffix)] + outputSuffix)
                            else:
                                witness = TimeStampFile(outputDir + inputFile[len(sourceDir):])
                            if not witness.exists():
                                return witness.path + ' does not exist'
                            if not self._newestOutput or witness.isNewerThan(self._newestOutput):
                                self._newestOutput = witness
                            if witness.isOlderThan(inputFile):
                                return '{} is older than {}'.format(witness, TimeStampFile(inputFile))
                            if newestInput and witness.isOlderThan(newestInput):
                                return '{} is older than {}'.format(witness, newestInput)
                    return None

                if not buildReason and checkBuildReason:
                    buildReason = findBuildReason()
        self.copyfiles = []
        if hasattr(self.subject, 'copyFiles'):
            for depname, copyMap in self.subject.copyFiles.items():
                dep = dependency(depname)
                if not dep.isProject():
                    abort("Unsupported dependency type: " + dep.name)
                deproot = dep.get_output_root()
                if dep.isNativeProject():
                    deproot = join(dep.suite.dir, dep.getOutput())
                for src, dst in copyMap.items():
                    absolute_src = join(deproot, src)
                    absolute_dst = join(outputDir, dst)
                    self.copyfiles += [(absolute_src, absolute_dst)]
                    witness = TimeStampFile(absolute_dst)
                    if not buildReason and checkBuildReason:
                        if not witness.exists():
                            buildReason = witness.path + ' does not exist'
                        if witness.isOlderThan(absolute_src):
                            buildReason = '{} is older than {}'.format(witness, TimeStampFile(absolute_src))
                    if witness.exists() and (not self._newestOutput or witness.isNewerThan(self._newestOutput)):
                        self._newestOutput = witness

        self.javafilelist = sorted(self.javafilelist)  # for reproducibility
        return buildReason

    def _getCompiler(self):
        if self._compiler is None:
            useJDT = self.args.jdt and not self.args.force_javac
            if hasattr(self.subject, 'forceJavac') and getattr(self.subject, 'forceJavac', False):
                # Revisit once GR-8992 is resolved
                logv('Project {} has "forceJavac" attribute set to True - falling back to javac'.format(self.subject))
                useJDT = False

            if useJDT and not _is_supported_by_jdt(self.jdk):
                # Revisit once GR-8852 is resolved
                logv('JDT does not yet support JDK9 - falling back to javac for ' + str(self.subject))
                useJDT = False

            if useJDT:
                if self.args.no_daemon:
                    self._compiler = ECJCompiler(self.jdk, self.args.jdt, self.args.extra_javac_args)
                else:
                    self._compiler = ECJDaemonCompiler(self.jdk, self.args.jdt, self.args.extra_javac_args)
            else:
                if self.args.no_daemon or self.args.alt_javac:
                    self._compiler = JavacCompiler(self.jdk, self.args.alt_javac, self.args.extra_javac_args)
                else:
                    self._compiler = JavacDaemonCompiler(self.jdk, self.args.extra_javac_args)
        return self._compiler

    def prepare(self, daemons):
        """
        Prepares the compilation that will be performed if `build` is called.

        :param dict daemons: map from keys to `Daemon` objects into which any daemons
                created to assist this task when `build` is called should be placed.
        """
        self.compiler = self._getCompiler()
        outputDir = ensure_dir_exists(self.subject.output_dir())
        if self._javaFileList():
            self.postCompileActions = []
            self.compileArgs = self.compiler.prepare(
                sourceFiles=[_cygpathU2W(f) for f in self._javaFileList()],
                project=self.subject,
                outputDir=_cygpathU2W(outputDir),
                classPath=_separatedCygpathU2W(classpath(self.subject.name, includeSelf=False, jdk=self.jdk, ignoreStripped=True)),
                sourceGenDir=self.subject.source_gen_dir(),
                jnigenDir=self.subject.jni_gen_dir(),
                processorPath=_separatedCygpathU2W(self.subject.annotation_processors_path(self.jdk)),
                disableApiRestrictions=not self.args.warnAPI,
                warningsAsErrors=self.args.warning_as_error,
                showTasks=self.args.jdt_show_task_tags,
                postCompileActions=self.postCompileActions,
                forceDeprecationAsWarning=self.args.force_deprecation_as_warning)
            self.compiler.prepare_daemon(daemons, self.compileArgs)
        else:
            self.compileArgs = None

    def build(self):
        outputDir = ensure_dir_exists(self.subject.output_dir())
        # Copy other files
        for nonjavafiletuple in self._nonJavaFileTuples():
            sourceDir = nonjavafiletuple[0]
            nonjavafilelist = nonjavafiletuple[1]
            for src in nonjavafilelist:
                dst = join(outputDir, src[len(sourceDir) + 1:])
                ensure_dir_exists(dirname(dst))
                dstFile = TimeStampFile(dst)
                if dstFile.isOlderThan(src):
                    shutil.copyfile(src, dst)
                    self._newestOutput = dstFile
        if self._nonJavaFileCount():
            logvv('Finished resource copy for {}'.format(self.subject.name))
        # Java build
        if self.compileArgs:
            try:
                self.compiler.compile(self.compileArgs)
            finally:
                for action in self.postCompileActions:
                    action()
            logvv('Finished Java compilation for {}'.format(self.subject.name))
            output = []
            for root, _, filenames in os.walk(outputDir):
                for fname in filenames:
                    output.append(os.path.join(root, fname))
            if output:
                self._newestOutput = TimeStampFile(max(output, key=getmtime))
        # Record current annotation processor config
        self.subject.update_current_annotation_processors_file()
        if self.copyfiles:
            for src, dst in self.copyfiles:
                ensure_dir_exists(dirname(dst))
                if not exists(dst) or getmtime(dst) < getmtime(src):
                    shutil.copyfile(src, dst)
                    self._newestOutput = TimeStampFile(dst)
            logvv('Finished copying files from dependencies for {}'.format(self.subject.name))

    def clean(self, forBuild=False):
        genDir = self.subject.source_gen_dir()
        if exists(genDir):
            logv('Cleaning {0}...'.format(genDir))
            for f in os.listdir(genDir):
                rmtree(join(genDir, f))

        outputDir = self.subject.output_dir()
        if exists(outputDir):
            logv('Cleaning {0}...'.format(outputDir))
            rmtree(outputDir)

        jnigenDir = self.subject.jni_gen_dir()
        if jnigenDir and exists(jnigenDir):
            logv('Cleaning {0}...'.format(jnigenDir))
            rmtree(jnigenDir)

### Compiler / Java Compiler

class JavaCompiler:
    def name(self):
        nyi('name', self)

    def prepare(self, sourceFiles, project, jdk, compliance, outputDir, classPath, processorPath, sourceGenDir, jnigenDir,
        disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, postCompileActions):
        """
        Prepares for a compilation with this compiler. This done in the main process.

        :param list sourceFiles: list of Java source files to compile
        :param JavaProject project: the project containing the source files
        :param JDKConfig jdk: the JDK used to execute this compiler
        :param JavaCompliance compliance:
        :param str outputDir: where to place generated class files
        :param str classpath: where to find user class files
        :param str processorPath: where to find annotation processors
        :param str sourceGenDir: where to place generated source files
        :param str jnigenDir: where to place generated JNI header files
        :param bool disableApiRestrictions: specifies if the compiler should not warning about accesses to restricted API
        :param bool warningsAsErrors: specifies if the compiler should treat warnings as errors
        :param bool forceDeprecationAsWarning: never treat deprecation warnings as errors irrespective of warningsAsErrors
        :param bool showTasks: specifies if the compiler should show tasks tags as warnings (JDT only)
        :param list postCompileActions: list into which callable objects can be added for performing post-compile actions
        :return: the value to be bound to `args` when calling `compile` to perform the compilation
        """
        nyi('prepare', self)

    def prepare_daemon(self, daemons, compileArgs):
        """
        Initializes any daemons used when `compile` is called with `compileArgs`.

        :param dict daemons: map from name to `CompilerDaemon` into which new daemons should be registered
        :param list compileArgs: the value bound to the `args` parameter when calling `compile`
        """

    def compile(self, jdk, args):
        """
        Executes the compilation that was prepared by a previous call to `prepare`.

        :param JDKConfig jdk: the JDK used to execute this compiler
        :param list args: the value returned by a call to `prepare`
        """
        nyi('compile', self)

class JavacLikeCompiler(JavaCompiler):
    def __init__(self, jdk, extraJavacArgs):
        self.jdk = jdk
        self.extraJavacArgs = extraJavacArgs if extraJavacArgs else []

    def prepare(self, sourceFiles, project, outputDir, classPath, processorPath, sourceGenDir, jnigenDir,
        disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, postCompileActions):
        javacArgs = ['-g', '-d', outputDir]
        compliance = project.javaCompliance
        if self.jdk.javaCompliance.value > 8 and compliance.value <= 8: # pylint: disable=chained-comparison
            # Ensure classes from dependencies take precedence over those in the JDK image.
            javacArgs.append('-Xbootclasspath/p:' + classPath)
        else:
            javacArgs += ['-classpath', classPath]
        if compliance.value >= 8:
            javacArgs.append('-parameters')
        if processorPath:
            ensure_dir_exists(sourceGenDir)
            javacArgs += ['-processorpath', processorPath, '-s', sourceGenDir]
        else:
            javacArgs += ['-proc:none']
        c = str(compliance)
        javacArgs += ['-target', c, '-source', c]
        if _opts.very_verbose:
            javacArgs.append('-verbose')

        javacArgs.extend(self.extraJavacArgs)

        fileList = join(project.get_output_root(), 'javafilelist.txt')
        with open(fileList, 'w') as fp:
            fp.write(os.linesep.join(sourceFiles))
        javacArgs.append('@' + _cygpathU2W(fileList))

        tempFiles = [fileList]
        if not _opts.verbose:
            # Only remove temporary files if not verbose so the user can copy and paste
            # the Java compiler command line directly to reproduce a failure.
            def _rm_tempFiles():
                for f in tempFiles:
                    os.remove(f)
            postCompileActions.append(_rm_tempFiles)

        return self.prepareJavacLike(project, javacArgs, disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, tempFiles, jnigenDir)

    def prepareJavacLike(self, project, javacArgs, disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, tempFiles, jnigenDir):
        nyi('buildJavacLike', self)

class JavacCompiler(JavacLikeCompiler):
    def __init__(self, jdk, altJavac=None, extraJavacArgs=None):
        JavacLikeCompiler.__init__(self, jdk, extraJavacArgs)
        self.altJavac = altJavac

    def name(self):
        return 'javac(JDK {})'.format(self.jdk.javaCompliance)

    def prepareJavacLike(self, project, javacArgs, disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, tempFiles, jnigenDir):
        jdk = self.jdk
        compliance = project.javaCompliance
        if jnigenDir is not None:
            javacArgs += ['-h', jnigenDir]

        lint = ['all', '-auxiliaryclass', '-processing', '-removal']
        overrides = project.get_javac_lint_overrides()
        if overrides:
            if 'none' in overrides:
                lint = ['none']
            else:
                lint += overrides
        if lint != ['none']:
            # https://blogs.oracle.com/darcy/new-javac-warning-for-setting-an-older-source-without-bootclasspath
            # Disable the "bootstrap class path not set in conjunction with -source N" warning
            # as we're relying on the Java compliance of project to correctly specify a JDK range
            # providing the API required by the project.
            lint += ['-options']

        if forceDeprecationAsWarning:
            lint += ['-deprecation']

        knownLints = jdk.getKnownJavacLints()
        if knownLints:
            lint = [l for l in lint if l in knownLints]
        if lint:
            javacArgs.append('-Xlint:' + ','.join(lint))

        if disableApiRestrictions:
            javacArgs.append('-XDignore.symbol.file')
        else:
            if jdk.javaCompliance >= '9':
                warn("Can not check all API restrictions on 9 (in particular sun.misc.Unsafe)")
        if warningsAsErrors:
            javacArgs.append('-Werror')
        if showTasks:
            abort('Showing task tags is not currently supported for javac')
        javacArgs.append('-encoding')
        javacArgs.append('UTF-8')
        javacArgs.append('-Xmaxerrs')
        javacArgs.append('10000')

        if jdk.javaCompliance >= '9':
            jdk_modules_overridden_on_classpath = set()  # pylint: disable=C0103
            declaringJdkModule = None

            def getDeclaringJDKModule(dep):
                """
                Gets the JDK module, if any, declaring at least one package in `dep`.
                """
                if dep.isJARDistribution():
                    return getattr(dep, 'moduleName', None)
                if not dep.isJavaProject() and not dep.isJARDistribution():
                    return None
                proj = dep
                m = getattr(proj, '.declaringJDKModule', None)
                if m is None:
                    # Look in modules declared in distributions first
                    for dist in sorted_dists():
                        moduleName = getattr(dist, 'moduleName', None)
                        if moduleName and proj in dist.archived_deps():
                            m = moduleName
                            break

                    if m is None:
                        # Now look in modules of the JDK
                        modulepath = jdk.get_modules()
                        java_packages = proj.defined_java_packages() | proj.extended_java_packages()
                        for package in java_packages:
                            jmd, _ = lookup_package(modulepath, package, "<unnamed>")
                            if jmd:
                                m = jmd.name
                                break
                    if m is None:
                        # Use proj to denote that proj is not declared by any JDK module
                        m = proj
                    setattr(proj, '.declaringJDKModule', m)
                if m is proj:
                    return None
                return m

            declaringJdkModule = getDeclaringJDKModule(project)
            if declaringJdkModule is not None:
                jdk_modules_overridden_on_classpath.add(declaringJdkModule)
                # If compiling sources for a JDK module, javac needs to know this via -Xmodule
                if jdk._javacXModuleOptionExists:
                    javacArgs.append('-Xmodule:' + declaringJdkModule)

            def addExportArgs(dep, exports=None, prefix='', jdk=None, observable_modules=None):
                """
                Adds ``--add-exports`` options (`JEP 261 <http://openjdk.java.net/jeps/261>`_) to
                `javacArgs` for the non-public JDK modules required by `dep`.

                :param mx.JavaProject dep: a Java project that may be dependent on private JDK modules
                :param dict exports: a set of exports per module for which ``--add-exports`` args
                   have already been added to `javacArgs`
                :param string prefix: the prefix to be added to the ``--add-exports`` arg(s)
                :param JDKConfig jdk: the JDK to be searched for concealed packages
                :param observable_modules: only consider modules in this set if not None
                """
                for module, packages in dep.get_concealed_imported_packages(jdk).items():
                    if observable_modules is not None and module not in observable_modules:
                        continue
                    if module in jdk_modules_overridden_on_classpath:
                        # If the classes in a JDK module declaring the dependency are also
                        # resolvable on the class path, then do not export the module
                        # as the class path classes are more recent than the module classes
                        continue
                    for package in packages:
                        exportedPackages = exports.setdefault(module, set())
                        if package not in exportedPackages:
                            exportedPackages.add(package)
                            exportArg = prefix + '--add-exports=' + module + '/' + package + '=ALL-UNNAMED'
                            javacArgs.append(exportArg)

            def addRootModules(exports, prefix):
                """
                Makes all modules in `exports` root modules since modules exported
                via ``--add-exports`` must be root modules.

                :param dict exports: a set of exports per module for which ``--add-exports`` args
                   have been added to `javacArgs`
                """
                if exports:
                    javacArgs.append(prefix + '--add-modules=' + ','.join(exports.keys()))

            if compliance >= '9':
                exports = {}
                entries = classpath_entries(project.name, includeSelf=False)
                for e in entries:
                    m = getDeclaringJDKModule(e)
                    if m:
                        jdk_modules_overridden_on_classpath.add(m)
                addExportArgs(project, exports)
                addRootModules(exports, '')
            aps = project.annotation_processors()
            if aps:
                # We want annotation processors to use classes on the class path
                # instead of those in modules since the module classes may not
                # be in exported packages and/or may have different signatures.
                # Unfortunately, there's no VM option for hiding modules, only the
                # --limit-modules option for restricting modules observability.
                # We limit module observability to those required by javac and
                # the module declaring sun.misc.Unsafe which is used by annotation
                # processors such as JMH.
                observable_modules = frozenset(['jdk.compiler', 'java.compiler', 'jdk.zipfs', 'jdk.unsupported'])

                exports = {}
                entries = classpath_entries(aps, preferProjects=True)
                for dep in entries:
                    m = getDeclaringJDKModule(dep)
                    if m:
                        jdk_modules_overridden_on_classpath.add(m)
                    elif dep.isJavaProject():
                        addExportArgs(dep, exports, '-J', jdk, observable_modules)

                # An annotation processor may have a dependency on other annotation
                # processors. The latter might need extra exports.
                entries = classpath_entries(aps, preferProjects=False)
                for dep in entries:
                    if dep.isJARDistribution() and dep.definedAnnotationProcessors:
                        for apDep in dep.deps:
                            m = getDeclaringJDKModule(apDep)
                            if m:
                                jdk_modules_overridden_on_classpath.add(m)
                            elif apDep.isJavaProject():
                                addExportArgs(apDep, exports, '-J', jdk, observable_modules)

                addRootModules(exports, '-J')

                if len(jdk_modules_overridden_on_classpath) != 0:
                    javacArgs.append('-J--limit-modules=' + ','.join(observable_modules))

        return javacArgs

    def compile(self, args):
        javac = self.altJavac if self.altJavac else self.jdk.javac
        cmd = [javac] + ['-J' + arg for arg in self.jdk.java_args] + args
        run(cmd)

class JavacDaemonCompiler(JavacCompiler):
    def __init__(self, jdk, extraJavacArgs=None):
        JavacCompiler.__init__(self, jdk, None, extraJavacArgs)

    def name(self):
        return 'javac-daemon(JDK {})'.format(self.jdk.javaCompliance)

    def compile(self, args):
        nonJvmArgs = [a for a in args if not a.startswith('-J')]
        return self.daemon.compile(nonJvmArgs)

    def prepare_daemon(self, daemons, compileArgs):
        jvmArgs = self.jdk.java_args + [a[2:] for a in compileArgs if a.startswith('-J')]
        key = 'javac-daemon:' + self.jdk.java + ' ' + ' '.join(jvmArgs)
        self.daemon = daemons.get(key)
        if not self.daemon:
            self.daemon = JavacDaemon(self.jdk, jvmArgs)
            daemons[key] = self.daemon

class Daemon:
    def shutdown(self):
        pass

class CompilerDaemon(Daemon):
    def __init__(self, jdk, jvmArgs, mainClass, toolJar, buildArgs=None):
        logv("Starting daemon for {} [{}]".format(jdk.java, ', '.join(jvmArgs)))
        self.jdk = jdk
        if not buildArgs:
            buildArgs = []
        build(buildArgs + ['--no-daemon', '--dependencies', 'com.oracle.mxtool.compilerserver'])
        cpArgs = get_runtime_jvm_args(names=['com.oracle.mxtool.compilerserver'], jdk=jdk, cp_suffix=toolJar)

        self.port = None
        self.portRegex = re.compile(r'Started server on port ([0-9]+)')

        # Start Java process asynchronously
        verbose = ['-v'] if _opts.verbose else []
        jobs = ['-j', str(cpu_count())]
        args = [jdk.java] + jvmArgs + cpArgs + [mainClass] + verbose + jobs
        preexec_fn, creationflags = _get_new_progress_group_args()
        if _opts.verbose:
            log(' '.join(map(pipes.quote, args)))
        p = subprocess.Popen(args, preexec_fn=preexec_fn, creationflags=creationflags, stdout=subprocess.PIPE) #pylint: disable=subprocess-popen-preexec-fn

        # scan stdout to capture the port number
        pout = []
        def redirect(stream):
            for line in iter(stream.readline, b''):
                line = _decode(line)
                pout.append(line)
                self._noticePort(line)
            stream.close()
        t = Thread(target=redirect, args=(p.stdout,))
        t.daemon = True
        t.start()

        # Ensure the process is cleaned up when mx exits
        _addSubprocess(p, args)

        # wait 30 seconds for the Java process to launch and report the port number
        retries = 0
        while self.port is None:
            retries = retries + 1
            returncode = p.poll()
            if returncode is not None:
                raise RuntimeError('Error starting ' + self.name() + ': returncode=' + str(returncode) + '\n' + ''.join(pout))
            if retries == 299:
                warn('Killing ' + self.name() + ' after failing to see port number after nearly 30 seconds')
                os.kill(p.pid, signal.SIGKILL)
                time.sleep(1.0)
            elif retries > 300:
                raise RuntimeError('Error starting ' + self.name() + ': No port number was found in output after 30 seconds\n' + ''.join(pout))
            else:
                time.sleep(0.1)

        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.connection.connect(('127.0.0.1', self.port))
            logv('[Started ' + str(self) + ']')
            return
        except socket.error as e:
            logv('[Error starting ' + str(self) + ': ' + str(e) + ']')
            raise e

    def _noticePort(self, data):
        logv(data.rstrip())
        if self.port is None:
            m = self.portRegex.match(data)
            if m:
                self.port = int(m.group(1))

    def compile(self, compilerArgs):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('127.0.0.1', self.port))
        logv(self.jdk.javac + ' ' + ' '.join(compilerArgs))
        commandLine = u'\x00'.join(compilerArgs)
        s.send((commandLine + '\n').encode('utf-8'))
        f = s.makefile()
        response = _unicode(f.readline())
        if response == '':
            # Compiler server process probably crashed
            logv('[Compiler daemon process appears to have crashed]')
            retcode = -1
        else:
            retcode = int(response)
        s.close()
        if retcode:
            if _opts.verbose:
                if _opts.very_verbose:
                    retcode = str(subprocess.CalledProcessError(retcode, self.jdk.javac + ' ' + ' '.join(compilerArgs)))
                else:
                    log('[exit code: ' + str(retcode) + ']')
            abort(retcode)

        return retcode

    def shutdown(self):
        try:
            self.connection.send('\n'.encode('utf8'))
            self.connection.close()
            logv('[Stopped ' + str(self) + ']')
        except socket.error as e:
            logv('Error stopping ' + str(self) + ': ' + str(e))

    def __str__(self):
        return self.name() + ' on port ' + str(self.port) + ' for ' + str(self.jdk)

class JavacDaemon(CompilerDaemon):
    def __init__(self, jdk, jvmArgs):
        CompilerDaemon.__init__(self, jdk, jvmArgs, 'com.oracle.mxtool.compilerserver.JavacDaemon', jdk.toolsjar, ['--force-javac'])

    def name(self):
        return 'javac-daemon'

class ECJCompiler(JavacLikeCompiler):
    def __init__(self, jdk, jdtJar, extraJavacArgs=None):
        JavacLikeCompiler.__init__(self, jdk, extraJavacArgs)
        self.jdtJar = jdtJar

    def name(self):
        return 'ecj(JDK {})'.format(self.jdk.javaCompliance)

    def prepareJavacLike(self, project, javacArgs, disableApiRestrictions, warningsAsErrors, forceDeprecationAsWarning, showTasks, tempFiles, jnigenDir):
        jdtArgs = javacArgs

        jdtProperties = join(project.dir, '.settings', 'org.eclipse.jdt.core.prefs')
        jdtPropertiesSources = project.eclipse_settings_sources()['org.eclipse.jdt.core.prefs']
        if not exists(jdtProperties) or TimeStampFile(jdtProperties).isOlderThan(jdtPropertiesSources):
            # Try to fix a missing or out of date properties file by running eclipseinit
            project._eclipseinit()
        if not exists(jdtProperties):
            log('JDT properties file {0} not found'.format(jdtProperties))
        else:
            with open(jdtProperties) as fp:
                origContent = fp.read()
                content = origContent
                if [ap for ap in project.declaredAnnotationProcessors if ap.isLibrary()]:
                    # unfortunately, the command line compiler doesn't let us ignore warnings for generated files only
                    content = content.replace('=warning', '=ignore')
                elif warningsAsErrors:
                    content = content.replace('=warning', '=error')
                if not showTasks:
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.tasks=ignore'
                if disableApiRestrictions:
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.forbiddenReference=ignore'
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.discouragedReference=ignore'

                if forceDeprecationAsWarning:
                    content = content.replace('org.eclipse.jdt.core.compiler.problem.deprecation=error', 'org.eclipse.jdt.core.compiler.problem.deprecation=warning')

            if origContent != content:
                jdtPropertiesTmp = jdtProperties + '.tmp'
                with open(jdtPropertiesTmp, 'w') as fp:
                    fp.write(content)
                tempFiles.append(jdtPropertiesTmp)
                jdtArgs += ['-properties', _cygpathU2W(jdtPropertiesTmp)]
            else:
                jdtArgs += ['-properties', _cygpathU2W(jdtProperties)]

        javahArgs = None
        if jnigenDir:
            def matchNative(line):
                # simple heuristic to match the keyword 'native' outside of comments or strings
                return re.match(r'[^"*/]*\bnative\b', line) is not None
            nativeClasses = project.find_classes_with_matching_source_line(None, matchNative).keys()
            if len(nativeClasses) == 0:
                abort('No native methods found in project {}, please remove the "jniHeaders" flag in suite.py.'.format(project.name), context=project)
            javahArgs = ['-d', jnigenDir, '-cp', classpath(project, jdk=self.jdk)] + list(nativeClasses)

        return (jdtArgs, javahArgs)

    def compile(self, compileArgs):
        (jdtArgs, javahArgs) = compileArgs
        run_java(['-jar', self.jdtJar] + jdtArgs, jdk=self.jdk)
        self.post_compile(javahArgs)

    def post_compile(self, javahArgs):
        if javahArgs is not None:
            if self.jdk.javah is None:
                abort('Cannot use ECJ on JDK without javah command.')
            run([self.jdk.javah] + javahArgs)

class ECJDaemonCompiler(ECJCompiler):
    def __init__(self, jdk, jdtJar, extraJavacArgs=None):
        ECJCompiler.__init__(self, jdk, jdtJar, extraJavacArgs)

    def name(self):
        return 'ecj-daemon(JDK {})'.format(self.jdk.javaCompliance)

    def compile(self, compileArgs):
        (jdtArgs, javahArgs) = compileArgs
        self.daemon.compile(jdtArgs)
        self.post_compile(javahArgs)

    def prepare_daemon(self, daemons, compileArgs):
        jvmArgs = self.jdk.java_args
        key = 'ecj-daemon:' + self.jdk.java + ' ' + ' '.join(jvmArgs)
        self.daemon = daemons.get(key)
        if not self.daemon:
            self.daemon = ECJDaemon(self.jdk, jvmArgs, self.jdtJar)
            daemons[key] = self.daemon

class ECJDaemon(CompilerDaemon):
    def __init__(self, jdk, jvmArgs, jdtJar):
        CompilerDaemon.__init__(self, jdk, jvmArgs, 'com.oracle.mxtool.compilerserver.ECJDaemon', jdtJar)

    def name(self):
        return 'ecj-daemon-server(JDK {})'.format(self.jdk.javaCompliance)


### ~~~~~~~~~~~~~ Project
class AbstractNativeProject(Project):
    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense=None, **kwargs):
        context = 'project ' + name
        self.buildDependencies = Suite._pop_list(kwargs, 'buildDependencies', context)
        super(AbstractNativeProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, theLicense,
                                                    **kwargs)

    def isPlatformDependent(self):
        return True


class NativeProject(AbstractNativeProject):
    """
    A NativeProject is a Project containing native code. It is built using `make`. The `MX_CLASSPATH` variable will be set
    to a classpath containing all JavaProject dependencies.
    Additional attributes:
      results: a list of result file names that will be packaged if the project is part of a distribution
      headers: a list of source file names (typically header files) that will be packaged if the project is part of a distribution
      output: the directory where the Makefile puts the `results`
      vpath: if `True`, make will be executed from the output root, with the `VPATH` environment variable set to the source directory
             if `False` or undefined, make will be executed from the source directory
      buildEnv: a dictionary of custom environment variables that are passed to the `make` process
    """
    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, results, output, d, theLicense=None, testProject=False, vpath=False, **kwArgs):
        super(NativeProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, theLicense, testProject=testProject, **kwArgs)
        self.results = results
        self.output = output
        self.vpath = vpath

    def getBuildTask(self, args):
        return NativeBuildTask(args, self)

    def getOutput(self, replaceVar=mx_subst.results_substitutions):
        if self.output:
            return mx_subst.as_engine(replaceVar).substitute(self.output, dependency=self)
        if self.vpath:
            return self.get_output_root()
        return None

    def getResults(self, replaceVar=mx_subst.results_substitutions):
        results = []
        output = self.getOutput(replaceVar=replaceVar)
        for rt in self.results:
            r = mx_subst.as_engine(replaceVar).substitute(rt, dependency=self)
            results.append(join(self.suite.dir, output, r))
        return results

    def getBuildEnv(self, replaceVar=mx_subst.path_substitutions):
        ret = {}
        if hasattr(self, 'buildEnv'):
            for key, value in self.buildEnv.items():
                ret[key] = replaceVar.substitute(value, dependency=self)
        return ret

    def getArchivableResults(self, use_relpath=True, single=False):
        if single:
            raise ValueError("single not supported")
        output = self.getOutput()
        output = join(self.suite.dir, output) if output else None
        for r in self.getResults():
            if output and use_relpath:
                filename = os.path.relpath(r, output)
            else:
                filename = basename(r)
            # Make debug-info files optional for distribution
            if is_debug_lib_file(r) and not os.path.exists(r):
                warn("File {} for archive {} does not exist.".format(filename, self.name))
            else:
                yield r, filename
        if hasattr(self, "headers"):
            srcdir = os.path.join(self.suite.dir, self.dir)
            for h in self.headers:
                if use_relpath:
                    filename = h
                else:
                    filename = basename(h)
                yield os.path.join(srcdir, h), filename


### ~~~~~~~~~~~~~ Build Tasks
class AbstractNativeBuildTask(ProjectBuildTask):
    def __init__(self, args, project):
        if hasattr(project, 'max_jobs'):
            jobs = min(int(project.max_jobs), cpu_count())
        else:
            # Cap jobs to maximum of 8 by default. If a project wants more parallelism, it can explicitly set the
            # "max_jobs" attribute. Setting jobs=cpu_count() would not allow any other tasks in parallel, now matter
            # how much parallelism the build machine supports.
            jobs = min(8, cpu_count())
        super(AbstractNativeBuildTask, self).__init__(args, jobs, project)

    def buildForbidden(self):
        if not self.args.native:
            return True
        return super(AbstractNativeBuildTask, self).buildForbidden()

    def cleanForbidden(self):
        if not self.args.native:
            return True
        return super(AbstractNativeBuildTask, self).cleanForbidden()

    def needsBuild(self, newestInput):
        is_needed, reason = super(AbstractNativeBuildTask, self).needsBuild(newestInput)
        if is_needed:
            return True, reason

        output = self.newestOutput()
        if output is None:
            return True, None

        return False, reason


class NativeBuildTask(AbstractNativeBuildTask):
    def __init__(self, args, project):
        super(NativeBuildTask, self).__init__(args, project)
        if hasattr(project, 'single_job') or not project.suite.getMxCompatibility().useJobsForMakeByDefault():
            self.parallelism = 1
        elif is_darwin() and not _opts.cpu_count:
            # work around darwin bug where make randomly fails in our CI (GR-6892) if compilation is too parallel
            self.parallelism = 1
        self._newestOutput = None

    def __str__(self):
        return 'Building {} with GNU Make'.format(self.subject.name)

    def _build_run_args(self):
        env = os.environ.copy()
        all_deps = self.subject.canonical_deps()
        if hasattr(self.subject, 'buildDependencies'):
            all_deps = set(all_deps) | set(self.subject.buildDependencies)
        javaDeps = [d for d in all_deps if isinstance(d, JavaProject)]
        if len(javaDeps) > 0:
            env['MX_CLASSPATH'] = classpath(javaDeps)
        cmdline = [gmake_cmd()]
        if _opts.verbose:
            # The Makefiles should have logic to disable the @ sign
            # so that all executed commands are visible.
            cmdline += ["MX_VERBOSE=y"]
        if hasattr(self.subject, "vpath") and self.subject.vpath:
            env['VPATH'] = self.subject.dir
            cwd = join(self.subject.suite.dir, self.subject.getOutput())
            ensure_dir_exists(cwd)
            cmdline += ['-f', join(self.subject.dir, 'Makefile')]
        else:
            cwd = self.subject.dir
        if hasattr(self.subject, "makeTarget"):
            cmdline += [self.subject.makeTarget]
        if hasattr(self.subject, "getBuildEnv"):
            env.update(self.subject.getBuildEnv())
        if self.parallelism > 1:
            cmdline += ['-j', str(self.parallelism)]
        return cmdline, cwd, env

    def build(self):
        cmdline, cwd, env = self._build_run_args()
        run(cmdline, cwd=cwd, env=env)
        self._newestOutput = None

    def needsBuild(self, newestInput):
        logv('Checking whether to build {} with GNU Make'.format(self.subject.name))
        cmdline, cwd, env = self._build_run_args()
        cmdline += ['-q']

        if _opts.verbose:
            # default out/err stream
            ret_code = run(cmdline, cwd=cwd, env=env, nonZeroIsFatal=False)
        else:
            with open(os.devnull, 'w') as fnull:
                # suppress out/err (redirect to null device)
                ret_code = run(cmdline, cwd=cwd, env=env, nonZeroIsFatal=False, out=fnull, err=fnull)

        if ret_code != 0:
            return (True, "rebuild needed by GNU Make")
        return (False, "up to date according to GNU Make")

    def newestOutput(self):
        if self._newestOutput is None:
            results = self.subject.getResults()
            self._newestOutput = None
            for r in results:
                ts = TimeStampFile(r, followSymlinks='newest')
                if ts.exists():
                    if not self._newestOutput or ts.isNewerThan(self._newestOutput):
                        self._newestOutput = ts
                else:
                    self._newestOutput = ts
                    break
        return self._newestOutput

    def clean(self, forBuild=False):
        if not forBuild:  # assume make can do incremental builds
            if hasattr(self.subject, "vpath") and self.subject.vpath:
                output = self.subject.getOutput()
                if os.path.exists(output) and output != '.':
                    shutil.rmtree(output)
            else:
                env = os.environ.copy()
                if hasattr(self.subject, "getBuildEnv"):
                    env.update(self.subject.getBuildEnv())
                run([gmake_cmd(), 'clean'], cwd=self.subject.dir, env=env)
            self._newestOutput = None

class Extractor(object):
    __metaclass__ = ABCMeta

    def __init__(self, src):
        self.src = src

    def extract(self, dst):
        logv("Extracting {} to {}".format(self.src, dst))
        with self._open() as ar:
            logv("Sanity checking archive...")
            if any((m for m in self._getnames(ar) if not self._is_sane_name(m, dst))):
                abort("Refusing to create files outside of the destination folder.\n" +
                      "Reasons might be entries with absolute paths or paths pointing to the parent directory (starting with `..`).\n" +
                      "Archive: {} \nProblematic files:\n{}".format(self.src, "\n".join((m for m in self._getnames(ar) if not self._is_sane_name(m, dst)))
                ))
            self._extractall(ar, dst)

    @abstractmethod
    def _open(self):
        pass

    @abstractmethod
    def _getnames(self, ar):
        pass

    @abstractmethod
    def _extractall(self, ar, dst):
        pass

    def _is_sane_name(self, m, dst):
        return os.path.realpath(os.path.join(dst, m)).startswith(os.path.realpath(dst))

    @staticmethod
    def create(src):
        if src.endswith(".tar") or src.endswith(".tar.gz"):
            return TarExtractor(src)
        if src.endswith(".zip"):
            return ZipExtractor(src)
        abort("Don't know how to extract the archive: " + src)


class TarExtractor(Extractor):

    def _open(self):
        return tarfile.open(self.src)

    def _getnames(self, ar):
        return ar.getnames()

    def _extractall(self, ar, dst):
        return ar.extractall(dst)


class ZipExtractor(Extractor):

    def _open(self):
        return zipfile.ZipFile(self.src)

    def _getnames(self, ar):
        return ar.namelist()

    def _extractall(self, ar, dst):
        return ar.extractall(dst)

### ~~~~~~~~~~~~~ Library

class BaseLibrary(Dependency):
    __metaclass__ = ABCMeta
    """
    A library that has no structure understood by mx, typically a jar file.
    It is used "as is".
    """
    def __init__(self, suite, name, optional, theLicense, **kwArgs):
        Dependency.__init__(self, suite, name, theLicense, **kwArgs)
        self.optional = optional

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        pass

    def resolveDeps(self):
        licenseId = self.theLicense
        # do not use suite's default license
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)

    def substVars(self, text):
        """
        Return string where references to instance variables from given text string are replaced.
        """
        return text.format(**vars(self))

    @abstractmethod
    def is_available(self):
        """
        Used to check whether an optional library is available.
        :rtype: bool
        """
        pass


class ResourceLibrary(BaseLibrary):
    """
    A library that is just a resource and therefore not a `ClasspathDependency`.
    """
    def __init__(self, suite, name, path, optional, urls, sha1, **kwArgs):
        BaseLibrary.__init__(self, suite, name, optional, None, **kwArgs)
        self.path = path.replace('/', os.sep) if path else None
        self.sourcePath = None
        self.urls = urls
        self.sha1 = sha1

    def getArchivableResults(self, use_relpath=True, single=False):
        path = realpath(self.get_path(False))
        yield path, _map_to_maven_dist_name(self.name) + '.' + get_file_extension(path)

    def getBuildTask(self, args):
        return LibraryDownloadTask(args, self)

    def is_available(self):
        if not self.path:
            return False
        return exists(self.get_path(True))

    def get_path(self, resolve):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        urls = [mx_urlrewrites.rewriteurl(self.substVars(url)) for url in self.urls]
        return download_file_with_sha1(self.name, path, urls, self.sha1, sha1path, resolve, not self.optional, canSymlink=True)

    def _check_download_needed(self):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        return not _check_file_with_sha1(path, self.sha1, sha1path)

    def _comparison_key(self):
        return (self.sha1, self.name)


class PackedResourceLibrary(ResourceLibrary):
    """
    A ResourceLibrary that comes in an archive and should be extraced after downloading.
    """

    def __init__(self, *args, **kwargs):
        super(PackedResourceLibrary, self).__init__(*args, **kwargs)
        # self.path points to the archive
        # self.extract_path points to the extracted content of the archive
        if not self.urls or not self.sha1:
            if not self.optional:
                abort("non-optional libraries must have urls and sha1")
            archive_path = None
        else:
            archive_path = _get_path_in_cache(self.name, self.sha1, self.urls, None, sources=False)
        if self.path == archive_path and archive_path is not None:
            # default path: generate path for extraction
            self.extract_path = _get_path_in_cache(self.name, self.sha1, self.urls, ".extracted", sources=False)
        else:
            # custom path: use generated path for archive and specified for the result
            self.extract_path = self.path
            self.path = archive_path

    def _check_extract_needed(self, dst, src):
        if not os.path.exists(dst):
            logvv("Destination does not exist")
            logvv("Destination: " + dst)
            return True
        if getmtime(src) > getmtime(dst):
            logvv("Destination older than source")
            logvv("Destination: " + dst)
            logvv("Source:      " + src)
            return True
        return False

    def is_available(self):
        if not self.extract_path:
            return False
        return exists(self.get_path(True))

    def get_path(self, resolve):
        extract_path = _make_absolute(self.extract_path, self.suite.dir)
        download_path = super(PackedResourceLibrary, self).get_path(resolve)
        if resolve and self._check_extract_needed(extract_path, download_path):
            extract_path_tmp = tempfile.mkdtemp(suffix=basename(extract_path), dir=dirname(extract_path))
            try:
                # extract archive
                Extractor.create(download_path).extract(extract_path_tmp)
                # ensure modification time is up to date
                os.utime(extract_path_tmp, None)
                logv("Moving temporary directory {} to {}".format(extract_path_tmp, extract_path))
                try:
                    # attempt atomic overwrite
                    os.rename(extract_path_tmp, extract_path)
                except OSError:
                    # clean destination & re-try for cases where atomic overwrite doesn't work
                    rmtree(extract_path, ignore_errors=True)
                    os.rename(extract_path_tmp, extract_path)
            except OSError as ose:
                # Rename failed. Race with other process?
                if self._check_extract_needed(extract_path, download_path):
                    # ok something really went wrong
                    abort("Extracting {} failed!".format(download_path), context=ose)
            finally:
                rmtree(extract_path_tmp, ignore_errors=True)

        return extract_path

    def _check_download_needed(self):
        need_download = super(PackedResourceLibrary, self)._check_download_needed()
        extract_path = _make_absolute(self.extract_path, self.suite.dir)
        download_path = _make_absolute(self.path, self.suite.dir)
        return need_download or self._check_extract_needed(extract_path, download_path)


class JreLibrary(BaseLibrary, ClasspathDependency):
    """
    A library jar provided by the Java Runtime Environment (JRE).

    This mechanism exists primarily to be able to support code
    that may use functionality in one JRE (e.g., Oracle JRE)
    that is not present in another JRE (e.g., OpenJDK). A
    motivating example is the Java Flight Recorder library
    found in the Oracle JRE.
    """
    def __init__(self, suite, name, jar, optional, theLicense, **kwArgs):
        BaseLibrary.__init__(self, suite, name, optional, theLicense, **kwArgs)
        ClasspathDependency.__init__(self, **kwArgs)
        self.jar = jar

    def _comparison_key(self):
        return self.jar

    def is_available(self):
        # This can not be answered without a JRE as context, see is_provided_by
        return True

    def is_provided_by(self, jdk):
        """
        Determines if this library is provided by `jdk`.

        :param JDKConfig jdk: the JDK to test
        :return: whether this library is available in `jdk`
        """
        return jdk.hasJarOnClasspath(self.jar)

    def getBuildTask(self, args):
        return NoOpTask(self, args)

    def classpath_repr(self, jdk, resolve=True):
        """
        Gets the absolute path of this library in `jdk`. This method will abort if this library is
        not provided by `jdk`.

        :param JDKConfig jdk: the JDK to test
        :return: whether this library is available in `jdk`
        """
        if not jdk:
            abort('A JDK is required to resolve ' + self.name + ' to a path')
        path = jdk.hasJarOnClasspath(self.jar)
        if not path:
            abort(self.name + ' is not provided by ' + str(jdk))
        return path

    def isJar(self):
        return True

### ~~~~~~~~~~~~~ Task

class NoOpTask(BuildTask):
    def __init__(self, subject, args):
        super(NoOpTask, self).__init__(subject, args, 1)

    def __str__(self):
        return "NoOp"

    def newestOutput(self):
        return None

    def execute(self):
        pass

    def build(self):
        pass

    def clean(self, forBuild=False):
        pass

### ~~~~~~~~~~~~~ Library

class JdkLibrary(BaseLibrary, ClasspathDependency):
    """
    A library that will be provided by the JDK but may be absent.
    Any project or normal library that depends on an optional missing library
    will be removed from the global project and library registry.

    :param Suite suite: the suite defining this library
    :param str name: the name of this library
    :param path: path relative to a JDK home directory where the jar file for this library is located
    :param deps: the dependencies of this library (which can only be other `JdkLibrary`s)
    :param bool optional: a missing non-optional library will cause mx to abort when resolving a reference to this library
    :param str theLicense: the license under which this library can be redistributed
    :param sourcePath: a path where the sources for this library are located. A relative path is resolved against a JDK.
    :param JavaCompliance jdkStandardizedSince: the JDK version in which the resources represented by this library are automatically
           available at compile and runtime without augmenting the class path. If not provided, ``1.2`` is used.
    :param module: If this JAR has been transferred to a module since JDK 9, the name of the module that contains the same classes as the JAR used to.
    """
    def __init__(self, suite, name, path, deps, optional, theLicense, sourcePath=None, jdkStandardizedSince=None, module=None, **kwArgs):
        BaseLibrary.__init__(self, suite, name, optional, theLicense, **kwArgs)
        ClasspathDependency.__init__(self, **kwArgs)
        self.path = path.replace('/', os.sep)
        self.sourcePath = sourcePath.replace('/', os.sep) if sourcePath else None
        self.deps = deps
        self.jdkStandardizedSince = jdkStandardizedSince if jdkStandardizedSince else JavaCompliance('1.2')
        self.module = module

    def resolveDeps(self):
        """
        Resolves symbolic dependency references to be Dependency objects.
        """
        BaseLibrary.resolveDeps(self)
        self._resolveDepsHelper(self.deps)
        for d in self.deps:
            if not d.isJdkLibrary():
                abort('"dependencies" attribute of a JDK library can only contain other JDK libraries: ' + d.name, context=self)

    def _comparison_key(self):
        return self.path

    def get_jdk_path(self, jdk, path):
        # Exploded JDKs don't have a jre directory.
        if exists(join(jdk.home, path)):
            return join(jdk.home, path)
        else:
            return join(jdk.home, 'jre', path)

    def is_available(self):
        # This can not be answered without a JDK as context, see is_provided_by
        return True

    def is_provided_by(self, jdk):
        """
        Determines if this library is provided by `jdk`.

        :param JDKConfig jdk: the JDK to test
        """
        return jdk.javaCompliance >= self.jdkStandardizedSince or exists(self.get_jdk_path(jdk, self.path))

    def getBuildTask(self, args):
        return NoOpTask(self, args)

    def classpath_repr(self, jdk, resolve=True):
        """
        Gets the absolute path of this library in `jdk` or None if this library is available
        on the default class path of `jdk`. This method will abort if this library is
        not provided by `jdk`.

        :param JDKConfig jdk: the JDK from which to retrieve this library's jar file
        :return: the absolute path of this library's jar file in `jdk`
        """
        if not jdk:
            abort('A JDK is required to resolve ' + self.name)
        if jdk.javaCompliance >= self.jdkStandardizedSince:
            return None
        path = self.get_jdk_path(jdk, self.path)
        if not exists(path):
            abort(self.name + ' is not provided by ' + str(jdk))
        return path

    def get_source_path(self, jdk):
        """
        Gets the path where the sources for this library are located.

        :param JDKConfig jdk: the JDK against which a relative path is resolved
        :return: the absolute path where the sources of this library are located
        """
        if self.sourcePath is None:
            return None
        if isabs(self.sourcePath):
            return self.sourcePath
        path = self.get_jdk_path(jdk, self.sourcePath)
        if not exists(path) and jdk.javaCompliance >= self.jdkStandardizedSince:
            return self.get_jdk_path(jdk, 'lib/src.zip')
        return path

    def isJar(self):
        return True

    def _walk_deps_visit_edges(self, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        deps = [(DEP_STANDARD, self.deps)]
        self._walk_deps_visit_edges_helper(deps, visited, in_edge, preVisit, visit, ignoredEdges, visitEdge)

class Library(BaseLibrary, ClasspathDependency):
    """
    A library that is provided (built) by some third-party and made available via a URL.
    A Library may have dependencies on other Library's as expressed by the "deps" field.
    A Library can only depend on another Library, and not a Project or Distribution
    Additional attributes are an SHA1 checksum, location of (assumed) matching sources.
    A Library is effectively an "import" into the suite since, unlike a Project or Distribution
    it is not built by the Suite.
    N.B. Not obvious but a Library can be an annotationProcessor
    """
    def __init__(self, suite, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps, theLicense, **kwArgs):
        BaseLibrary.__init__(self, suite, name, optional, theLicense, **kwArgs)
        ClasspathDependency.__init__(self, **kwArgs)
        self.path = path.replace('/', os.sep) if path is not None else None
        self.urls = urls
        self.sha1 = sha1
        self.sourcePath = sourcePath.replace('/', os.sep) if sourcePath else None
        self.sourceUrls = sourceUrls
        if sourcePath == path:
            assert sourceSha1 is None or sourceSha1 == sha1
            sourceSha1 = sha1
        self.sourceSha1 = sourceSha1
        self.deps = deps
        if not optional:
            abspath = _make_absolute(path, self.suite.dir)
            if not exists(abspath) and not len(urls):
                abort('Non-optional library {0} must either exist at {1} or specify one or more URLs from which it can be retrieved'.format(name, abspath), context=self)

            def _checkSha1PropertyCondition(propName, cond, inputPath):
                if not cond:
                    absInputPath = _make_absolute(inputPath, self.suite.dir)
                    if exists(absInputPath):
                        abort('Missing "{0}" property for library {1}. Add the following to the definition of {1}:\n{0}={2}'.format(propName, name, sha1OfFile(absInputPath)), context=self)
                    abort('Missing "{0}" property for library {1}'.format(propName, name), context=self)

            _checkSha1PropertyCondition('sha1', sha1, path)
            _checkSha1PropertyCondition('sourceSha1', not sourcePath or sourceSha1, sourcePath)

        for url in urls:
            if url.endswith('/') != self.path.endswith(os.sep):
                abort('Path for dependency directory must have a URL ending with "/": path=' + self.path + ' url=' + url, context=self)

    def resolveDeps(self):
        """
        Resolves symbolic dependency references to be Dependency objects.
        """
        BaseLibrary.resolveDeps(self)
        self._resolveDepsHelper(self.deps)

    def _walk_deps_visit_edges(self, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        deps = [(DEP_STANDARD, self.deps)]
        self._walk_deps_visit_edges_helper(deps, visited, in_edge, preVisit, visit, ignoredEdges, visitEdge)

    def _comparison_key(self):
        return (self.sha1, self.name)

    def get_urls(self):
        return [mx_urlrewrites.rewriteurl(self.substVars(url)) for url in self.urls]

    def is_available(self):
        if not self.path:
            return False
        return exists(self.get_path(True))

    def get_path(self, resolve):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'

        bootClassPathAgent = getattr(self, 'bootClassPathAgent').lower() == 'true' if hasattr(self, 'bootClassPathAgent') else False

        urls = self.get_urls()
        return download_file_with_sha1(self.name, path, urls, self.sha1, sha1path, resolve, not self.optional, canSymlink=not bootClassPathAgent)

    def _check_download_needed(self):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        if not _check_file_with_sha1(path, self.sha1, sha1path):
            return True
        if self.sourcePath:
            path = _make_absolute(self.sourcePath, self.suite.dir)
            sha1path = path + '.sha1'
            if not _check_file_with_sha1(path, self.sourceSha1, sha1path):
                return True
        return False

    def get_source_path(self, resolve):
        if self.sourcePath is None:
            return None
        path = _make_absolute(self.sourcePath, self.suite.dir)
        sha1path = path + '.sha1'

        sourceUrls = [mx_urlrewrites.rewriteurl(self.substVars(url)) for url in self.sourceUrls]
        return download_file_with_sha1(self.name, path, sourceUrls, self.sourceSha1, sha1path, resolve, len(self.sourceUrls) != 0, sources=True)

    def classpath_repr(self, resolve=True):
        path = self.get_path(resolve)
        if path and (exists(path) or not resolve):
            return path
        return None

    def getBuildTask(self, args):
        return LibraryDownloadTask(args, self)

    def getArchivableResults(self, use_relpath=True, single=False):
        path = realpath(self.get_path(False))
        yield path, _map_to_maven_dist_name(self.name) + '.' + get_file_extension(path)
        if not single:
            src_path = self.get_source_path(False)
            if src_path:
                src_path = realpath(src_path)
                ext = get_file_extension(src_path)
                if 'src' not in ext and 'source' not in ext:
                    ext = "src." + ext
                src_filename = _map_to_maven_dist_name(self.name) + '.' + ext
                yield src_path, src_filename


class LibraryDownloadTask(BuildTask):
    def __init__(self, args, lib):
        BuildTask.__init__(self, lib, args, 1)  # TODO use all CPUs to avoid output problems?

    def __str__(self):
        return "Downloading {}".format(self.subject.name)

    def logBuild(self, reason=None):
        pass

    def logSkip(self, reason=None):
        pass

    def needsBuild(self, newestInput):
        sup = BuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        return (self.subject._check_download_needed(), None)

    def newestOutput(self):
        return TimeStampFile(_make_absolute(self.subject.path, self.subject.suite.dir))

    def build(self):
        self.subject.get_path(resolve=True)
        if hasattr(self.subject, 'get_source_path'):
            self.subject.get_source_path(resolve=True)

    def clean(self, forBuild=False):
        abort('should not reach here')

    def cleanForbidden(self):
        return True

### ~~~~~~~~~~~~~ Version control

"""
Abstracts the operations of the version control systems
Most operations take a vcdir as the dir in which to execute the operation
Most operations abort on error unless abortOnError=False, and return True
or False for success/failure.

Potentially long running operations should log the command. If '-v' is set
'run'  will log the actual VC command. If '-V' is set the output from
the command should be logged.
"""
class VC(object):
    __metaclass__ = ABCMeta
    """
    base class for all supported Distriuted Version Constrol abstractions

    :ivar str kind: the VC type identifier
    :ivar str proper_name: the long name descriptor of the VCS
    """

    def __init__(self, kind, proper_name):
        self.kind = kind
        self.proper_name = proper_name

    @staticmethod
    def is_valid_kind(kind):
        """
        tests if the given VCS kind is valid or not

        :param str kind: the VCS kind
        :return: True if a valid VCS kind
        :rtype: bool
        """
        for vcs in _vc_systems:
            if kind == vcs.kind:
                return True
        return False

    @staticmethod
    def get_vc(vcdir, abortOnError=True):
        """
        Given that `vcdir` is a repository directory, attempt to determine
        what kind of VCS is it managed by. Return None if it cannot be determined.

        :param str vcdir: a valid path to a version controlled directory
        :param bool abortOnError: if an error occurs, abort mx operations
        :return: an instance of VC or None if it cannot be determined
        :rtype: :class:`VC`
        """
        for vcs in _vc_systems:
            vcs.check()
            if vcs.is_this_vc(vcdir):
                return vcs
        if abortOnError:
            abort('cannot determine VC for ' + vcdir)
        else:
            return None

    @staticmethod
    def get_vc_root(directory, abortOnError=True):
        """
        Attempt to determine what kind of VCS is associated with `directory`.
        Return the VC and its root directory or (None, None) if it cannot be determined.

        If `directory` is contained in multiple VCS, the one with the deepest nesting is returned.

        :param str directory: a valid path to a potentially version controlled directory
        :param bool abortOnError: if an error occurs, abort mx operations
        :return: a tuple containing an instance of VC or None if it cannot be
        determined followed by the root of the repository or None.
        :rtype: :class:`VC`, str
        """
        best_root = None
        best_vc = None
        for vcs in _vc_systems:
            vcs.check()
            root = vcs.root(directory, abortOnError=False)
            if root is None:
                continue
            root = realpath(os.path.abspath(root))
            if best_root is None or len(root) > len(best_root):  # prefer more nested vcs roots
                best_root = root
                best_vc = vcs
        if abortOnError and best_root is None:
            abort('cannot determine VC and root for ' + directory)
        return best_vc, best_root

    def check(self, abortOnError=True):
        """
        Lazily check whether a particular VC system is available.
        Return None if fails and abortOnError=False
        """
        abort("VC.check is not implemented")

    def init(self, vcdir, abortOnError=True):
        """
        Intialize 'vcdir' for vc control
        """
        abort(self.kind + " init is not implemented")

    def is_this_vc(self, vcdir):
        """
        Check whether vcdir is managed by this vc.
        Return None if not, True if so
        """
        abort(self.kind + " is_this_vc is not implemented")

    def metadir(self):
        """
        Return name of metadata directory
        """
        abort(self.kind + " metadir is not implemented")

    def add(self, vcdir, path, abortOnError=True):
        """
        Add path to repo
        """
        abort(self.kind + " add is not implemented")

    def commit(self, vcdir, msg, abortOnError=True):
        """
        commit with msg
        """
        abort(self.kind + " commit is not implemented")

    def tip(self, vcdir, abortOnError=True):
        """
        Get the most recent changeset for repo at `vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        abort(self.kind + " tip is not implemented")

    def parent(self, vcdir, abortOnError=True):
        """
        Get the parent changeset of the working directory for repo at `vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        abort(self.kind + " id is not implemented")

    def parent_info(self, vcdir, abortOnError=True):
        """
        Get the dict with common commit information.

        The following fields are provided in the dict:

        - author: name <e-mail> (best-effort, might only contain a name)
        - author-ts: unix timestamp (int)
        - committer: name <e-mail> (best-effort, might only contain a name)
        - committer-ts: unix timestamp (int)
        - description: Commit description

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on error
        :return: dictionary with information key-value pairs
        :rtype: dict
        """
        abort(self.kind + " parent_info is not implemented")

    def _sanitize_parent_info(self, info):
        """Utility method to sanitize the parent_info dictionary.

        Converts integer fields to actual ints, and strips.
        """
        def strip(field):
            info[field] = info[field].strip()
        def to_int(field):
            info[field] = int(info[field].strip())
        to_int("author-ts")
        to_int("committer-ts")
        strip("author")
        strip("committer")
        return info

    def active_branch(self, vcdir, abortOnError=True):
        """
        Returns the active branch of the repository

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on error
        :return: name of the branch
        :rtype: str
        """
        abort(self.kind + " active_branch is not implemented")

    def update_to_branch(self, vcdir, branch, abortOnError=True):
        """
        Update to a branch a make it active.

        :param str vcdir: a valid repository path
        :param str branch: a branch name
        :param bool abortOnError: if True abort on error
        """
        abort(self.kind + " update_to_branch is not implemented")

    def is_release_from_tags(self, vcdir, prefix):
        """
        Returns True if the release version derived from VC tags matches the pattern <number>(.<number>)*.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix
        :return: True if release
        :rtype: bool
        """
        _release_version = self.release_version_from_tags(vcdir=vcdir, prefix=prefix) #pylint: disable=assignment-from-no-return
        return _release_version and re.match(r'^[0-9]+[0-9.]+$', _release_version)

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        """
        Returns a release version derived from VC tags that match the pattern <prefix>-<number>(.<number>)*
        or None if no such tags exist.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix
        :param str snapshotSuffix: the snapshot suffix
        :param bool abortOnError: if True abort on mx error
        :return: a release version
        :rtype: str
        """
        abort(self.kind + " release_version_from_tags is not implemented")

    def parent_tags(self, vcdir):
        """
        Returns the tags of the parent revision.

        :param str vcdir: a valid repository path
        :rtype: list of str
        """
        abort(self.kind + " parent_tags is not implemented")

    @staticmethod
    def _version_string_helper(current_revision, tag_revision, tag_version, snapshotSuffix):
        def version_str(version_list):
            return '.'.join((str(a) for a in version_list))

        if current_revision == tag_revision:
            return version_str(tag_version)
        else:
            next_version = list(tag_version)
            next_version[-1] += 1
            return version_str(next_version) + '-' + snapshotSuffix

    @staticmethod
    def _find_metadata_dir(start, name):
        d = start
        while len(d) != 0 and os.path.splitdrive(d)[1] != os.sep:
            subdir = join(d, name)
            if exists(subdir):
                return subdir
            d = dirname(d)
        return None

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        """
        Clone the repo at `url` to `dest` using `rev`

        :param str url: the repository url
        :param str dest: the path to destination, if None the destination is
                         chosen by the vcs
        :param str rev: the desired revision, if None use tip
        :param dict extra_args: for subclass-specific information in/out
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        abort(self.kind + " clone is not implemented")

    def _log_clone(self, url, dest=None, rev=None):
        msg = 'Cloning ' + url
        if rev:
            msg += ' revision ' + rev
        if dest:
            msg += ' to ' + dest
        msg += ' with ' + self.proper_name
        log(msg)

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        """
        Pull a given changeset (the head if `rev` is None), optionally updating
        the working directory. Updating is only done if something was pulled.
        If there were no new changesets or `rev` was already known locally,
        no update is performed.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision, if None use tip
        :param bool abortOnError: if True abort on mx error
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        abort(self.kind + " pull is not implemented")

    def _log_pull(self, vcdir, rev):
        msg = 'Pulling'
        if rev:
            msg += ' revision ' + rev
        else:
            msg += ' head updates'
        msg += ' in ' + vcdir
        msg += ' with ' + self.proper_name
        log(msg)

    def can_push(self, vcdir, strict=True):
        """
        Check if `vcdir` can be pushed.

        :param str vcdir: a valid repository path
        :param bool strict: if set no uncommitted changes or unadded are allowed
        :return: True if we can push, False otherwise
        :rtype: bool
        """

    def default_push(self, vcdir, abortOnError=True):
        """
        get the default push target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default push target for repo
        :rtype: str
        """
        abort(self.kind + " default_push is not implemented")

    def default_pull(self, vcdir, abortOnError=True):
        """
        get the default pull target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default pull target for repo
        :rtype: str
        """
        abort(self.kind + " default_pull is not implemented")

    def incoming(self, vcdir, abortOnError=True):
        """
        list incoming changesets

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        abort(self.kind + ": outgoing is not implemented")

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        """
        llist outgoing changesets to 'dest' or default-push if None

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        abort(self.kind + ": outgoing is not implemented")

    def push(self, vcdir, dest=None, rev=None, abortOnError=False):
        """
        Push `vcdir` at rev `rev` to default if `dest`
        is None, else push to `dest`.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param str dest: the path to destination
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + ": push is not implemented")

    def _log_push(self, vcdir, dest, rev):
        msg = 'Pushing changes'
        if rev:
            msg += ' revision ' + rev
        msg += ' from ' + vcdir
        if dest:
            msg += ' to ' + dest
        else:
            msg += ' to default'
        msg += ' with ' + self.proper_name
        log(msg)

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        """
        update the `vcdir` working directory.
        If `rev` is not specified, update to the tip of the current branch.
        If `rev` is specified, `mayPull` controls whether a pull will be attempted if
        `rev` can not be found locally.
        If `clean` is True, uncommitted changes will be discarded (no backup!).

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param bool mayPull: flag to controll whether to pull or not
        :param bool clean: discard uncommitted changes without backing up
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + " update is not implemented")

    def isDirty(self, vcdir, abortOnError=True):
        """
        check whether the working directory is dirty

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True of the working directory is dirty, False otherwise
        :rtype: bool
        """
        abort(self.kind + " isDirty is not implemented")

    def status(self, vcdir, abortOnError=True):
        """
        report the status of the repository

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + " status is not implemented")

    def locate(self, vcdir, patterns=None, abortOnError=True):
        """
        Return a list of paths under vc control that match `patterns`

        :param str vcdir: a valid repository path
        :param patterns: a list of patterns
        :type patterns: str or None or list
        :param bool abortOnError: if True abort on mx error
        :return: a list of paths under vc control
        :rtype: list
        """
        abort(self.kind + " locate is not implemented")

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        """
        Place a bookmark at a given revision

        :param str vcdir: a valid repository path
        :param str name: the name of the bookmark
        :param str rev: the desired revision
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + " bookmark is not implemented")

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        """
        Returns the latest of 2 revisions.
        The revisions should be related in the DAG.

        :param str vcdir: a valid repository path
        :param str rev1: the first revision
        :param str rev2: the second revision
        :param bool abortOnError: if True abort on mx error
        :return: the latest of the 2 revisions
        :rtype: str or None
        """
        abort(self.kind + " latest is not implemented")

    def exists(self, vcdir, rev):
        """
        Check if a given revision exists in the repository.

        :param str vcdir: a valid repository path
        :param str rev: the second revision
        :return: True if revision exists, False otherwise
        :rtype: bool
        """
        abort(self.kind + " exists is not implemented")

    def root(self, directory, abortOnError=True):
        """
        Returns the path to the root of the repository that contains `dir`.

        :param str dir: a path to a directory contained in a repository.
        :param bool abortOnError: if True abort on mx error
        :return: The path to the repository's root
        :rtype: str or None
        """
        abort(self.kind + " root is not implemented")


class OutputCapture:
    def __init__(self):
        self.data = ""
    def __call__(self, data):
        self.data += data

class LinesOutputCapture:
    def __init__(self):
        self.lines = []
    def __call__(self, data):
        self.lines.append(data.rstrip())

class TeeOutputCapture:
    def __init__(self, underlying):
        self.underlying = underlying
    def __call__(self, data):
        log(data.rstrip())
        self.underlying(data)

class HgConfig(VC):
    has_hg = None
    """
    Encapsulates access to Mercurial (hg)
    """
    def __init__(self):
        VC.__init__(self, 'hg', 'Mercurial')
        self.missing = 'no hg executable found'

    def check(self, abortOnError=True):
        # Mercurial does lazy checking before use of the hg command itself
        return self

    def check_for_hg(self, abortOnError=True):
        if HgConfig.has_hg is None:
            try:
                _check_output_str(['hg'])
                HgConfig.has_hg = True
            except OSError:
                HgConfig.has_hg = False

        if not HgConfig.has_hg:
            if abortOnError:
                abort(self.missing)

        return self if HgConfig.has_hg else None

    def run(self, *args, **kwargs):
        # Ensure hg exists before executing the command
        self.check_for_hg()
        return run(*args, **kwargs)

    def init(self, vcdir, abortOnError=True):
        return self.run(['hg', 'init', vcdir], nonZeroIsFatal=abortOnError) == 0

    def is_this_vc(self, vcdir):
        hgdir = join(vcdir, self.metadir())
        return os.path.isdir(hgdir)

    def active_branch(self, vcdir, abortOnError=True):
        out = OutputCapture()
        cmd = ['hg', 'bookmarks']
        rc = self.run(cmd, nonZeroIsFatal=False, cwd=vcdir, out=out)
        if rc == 0:
            for line in out.data.splitlines():
                if line.strip().startswith(' * '):
                    return line[3:].split(" ")[0]
        if abortOnError:
            abort('no active hg bookmark found')
        return None

    def update_to_branch(self, vcdir, branch, abortOnError=True):
        cmd = ['update', branch]
        self.hg_command(vcdir, cmd, abortOnError=abortOnError)

    def add(self, vcdir, path, abortOnError=True):
        return self.run(['hg', '-q', '-R', vcdir, 'add', path]) == 0

    def commit(self, vcdir, msg, abortOnError=True):
        return self.run(['hg', '-R', vcdir, 'commit', '-m', msg]) == 0

    def tip(self, vcdir, abortOnError=True):
        self.check_for_hg()
        # We don't use run because this can be called very early before _opts is set
        try:
            return _check_output_str(['hg', 'tip', '-R', vcdir, '--template', '{node}'])
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('hg tip failed')
            else:
                return None

    def parent(self, vcdir, abortOnError=True):
        self.check_for_hg()
        # We don't use run because this can be called very early before _opts is set
        try:
            out = _check_output_str(['hg', '-R', vcdir, 'parents', '--template', '{node}\n'])
            parents = out.rstrip('\n').split('\n')
            if len(parents) != 1:
                if abortOnError:
                    abort('hg parents returned {} parents (expected 1)'.format(len(parents)))
                return None
            return parents[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('hg parents failed')
            else:
                return None

    def parent_info(self, vcdir, abortOnError=True):
        out = self.hg_command(vcdir, ["log", "-r", ".", "--template", "{author}|||{date|hgdate}"], abortOnError=abortOnError)
        author, date = out.split("|||")
        ts, _ = date.split(" ")
        return self._sanitize_parent_info({
            "author": author,
            "author-ts": ts,
            "committer": author,
            "committer-ts": ts,
        })

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        prefix = prefix + '-'
        try:
            tagged_ids_out = _check_output_str(['hg', '-R', vcdir, 'log', '--rev', 'ancestors(.) and tag()', '--template', '{tags},{rev}\n'])
            tagged_ids = [x.split(',') for x in tagged_ids_out.split('\n') if x]
            current_id = _check_output_str(['hg', '-R', vcdir, 'log', '--template', '{rev}\n', '--rev', '.']).strip()
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('hg tags or hg tip failed: ' + str(e))
            else:
                return None

        if tagged_ids and current_id:
            def first(it):
                try:
                    v = next(it)
                    return v
                except StopIteration:
                    return None
            tag_re = re.compile(r"^{0}[0-9]+\.[0-9]+$".format(prefix))
            tagged_ids = [(first((tag for tag in tags.split(' ') if tag_re.match(tag))), revid) for tags, revid in tagged_ids]
            tagged_ids = [(tag, revid) for tag, revid in tagged_ids if tag]
            version_ids = [([int(x) for x in tag[len(prefix):].split('.')], revid) for tag, revid in tagged_ids]
            version_ids = sorted(version_ids, key=lambda e: e[0], reverse=True)
            most_recent_tag_version, most_recent_tag_id = version_ids[0]
            return VC._version_string_helper(current_id, most_recent_tag_id, most_recent_tag_version, snapshotSuffix)
        return None

    def parent_tags(self, vcdir):
        try:
            _tags = _check_output_str(['hg', '-R', vcdir, 'log', '--template', '{tags}', '--rev', '.']).strip().split(' ')
            return [tag for tag in _tags if tag != 'tip']
        except subprocess.CalledProcessError as e:
            abort('hg log failed: ' + str(e))

    def metadir(self):
        return '.hg'

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        cmd = ['hg', 'clone']
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        cmd.append(url)
        if dest:
            cmd.append(dest)
        self._log_clone(url, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def incoming(self, vcdir, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'incoming'], nonZeroIsFatal=False, out=out)
        if rc in (0, 1):
            return out.data
        else:
            if abortOnError:
                abort('incoming returned ' + str(rc))
            return None

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        out = OutputCapture()
        cmd = ['hg', '-R', vcdir, 'outgoing']
        if dest:
            cmd.append(dest)
        rc = self.run(cmd, nonZeroIsFatal=False, out=out)
        if rc in (0, 1):
            return out.data
        else:
            if abortOnError:
                abort('outgoing returned ' + str(rc))
            return None

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        cmd = ['hg', 'pull', '-R', vcdir]
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        if update:
            cmd.append('-u')
        self._log_pull(vcdir, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def can_push(self, vcdir, strict=True, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'status'], nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            if strict:
                return output == ''
            else:
                if len(output) > 0:
                    for line in output.split('\n'):
                        if len(line) > 0 and not line.startswith('?'):
                            return False
                return True
        else:
            return False

    def _path(self, vcdir, name, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'paths'], nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            prefix = name + ' = '
            for line in output.split(os.linesep):
                if line.startswith(prefix):
                    return line[len(prefix):]
        if abortOnError:
            abort("no '{}' path for repository {}".format(name, vcdir))
        return None

    def default_push(self, vcdir, abortOnError=True):
        push = self._path(vcdir, 'default-push', abortOnError=False)
        if push:
            return push
        return self.default_pull(vcdir, abortOnError=abortOnError)

    def default_pull(self, vcdir, abortOnError=True):
        return self._path(vcdir, 'default', abortOnError=abortOnError)

    def push(self, vcdir, dest=None, rev=None, abortOnError=False):
        cmd = ['hg', '-R', vcdir, 'push']
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        if dest:
            cmd.append(dest)
        self._log_push(vcdir, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        if rev and mayPull and not self.exists(vcdir, rev):
            self.pull(vcdir, rev=rev, update=False, abortOnError=abortOnError)
        cmd = ['hg', '-R', vcdir, 'update']
        if rev:
            cmd += ['-r', rev]
        if clean:
            cmd += ['-C']
        return self.run(cmd, nonZeroIsFatal=abortOnError) == 0

    def locate(self, vcdir, patterns=None, abortOnError=True):
        if patterns is None:
            patterns = []
        elif not isinstance(patterns, list):
            patterns = [patterns]
        out = LinesOutputCapture()
        rc = self.run(['hg', 'locate', '-R', vcdir] + patterns, out=out, nonZeroIsFatal=False)
        if rc == 1:
            # hg locate returns 1 if no matches were found
            return []
        elif rc == 0:
            return out.lines
        else:
            if abortOnError:
                abort('locate returned: ' + str(rc))
            else:
                return None

    def isDirty(self, vcdir, abortOnError=True):
        self.check_for_hg()
        try:
            return len(_check_output_str(['hg', 'status', '-q', '-R', vcdir])) > 0
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get status')
            else:
                return None

    def status(self, vcdir, abortOnError=True):
        cmd = ['hg', '-R', vcdir, 'status']
        return self.run(cmd, nonZeroIsFatal=abortOnError) == 0

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        ret = run(['hg', '-R', vcdir, 'bookmark', '-r', rev, '-i', '-f', name], nonZeroIsFatal=False)
        if ret != 0:
            logging = abort if abortOnError else warn
            logging("Failed to create bookmark {0} at revision {1} in {2}".format(name, rev, vcdir))

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        #hg log -r 'heads(ancestors(26030a079b91) and ancestors(6245feb71195))' --template '{node}\n'
        self.check_for_hg()
        try:
            revs = [rev1, rev2]
            revsetIntersectAncestors = ' or '.join(('ancestors({})'.format(rev) for rev in revs))
            revset = 'heads({})'.format(revsetIntersectAncestors)
            out = _check_output_str(['hg', '-R', vcdir, 'log', '-r', revset, '--template', '{node}\n'])
            parents = out.rstrip('\n').split('\n')
            if len(parents) != 1:
                if abortOnError:
                    abort('hg log returned {} possible latest (expected 1)'.format(len(parents)))
                return None
            return parents[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('latest failed')
            else:
                return None

    def exists(self, vcdir, rev):
        self.check_for_hg()
        try:
            sentinel = 'exists'
            out = _check_output_str(['hg', '-R', vcdir, 'log', '-r', 'present({})'.format(rev), '--template', sentinel])
            return sentinel in out
        except subprocess.CalledProcessError:
            abort('exists failed')

    def root(self, directory, abortOnError=True):
        metadata = VC._find_metadata_dir(directory, '.hg')
        if metadata:
            try:
                out = _check_output_str(['hg', 'root'], cwd=directory, stderr=subprocess.STDOUT)
                return out.strip()
            except subprocess.CalledProcessError:
                if abortOnError:
                    self.check_for_hg()
                    abort('hg root failed')
                else:
                    return None
        else:
            if abortOnError:
                abort('No .hg directory')
            else:
                return None


class GitConfig(VC):
    has_git = None
    """
    Encapsulates access to Git (git)
    """
    def __init__(self):
        VC.__init__(self, 'git', 'Git')
        self.missing = 'No Git executable found. You must install Git in order to proceed!'
        self.object_cache_mode = get_env('MX_GIT_CACHE') or None
        if self.object_cache_mode not in [None, 'reference', 'dissociated', 'refcache']:
            abort("MX_GIT_CACHE was '{}' expected '', 'reference', 'dissociated' or 'refcache'")

    def check(self, abortOnError=True):
        return self

    def check_for_git(self, abortOnError=True):
        if GitConfig.has_git is None:
            try:
                _check_output_str(['git', '--version'])
                GitConfig.has_git = True
            except OSError:
                GitConfig.has_git = False

        if not GitConfig.has_git:
            if abortOnError:
                abort(self.missing)

        return self if GitConfig.has_git else None

    def run(self, *args, **kwargs):
        # Ensure git exists before executing the command
        self.check_for_git()
        return run(*args, **kwargs)

    def init(self, vcdir, abortOnError=True, bare=False):
        cmd = ['git', 'init']
        if bare:
            cmd.append('--bare')
        cmd.append(vcdir)
        return self.run(cmd, nonZeroIsFatal=abortOnError) == 0

    def is_this_vc(self, vcdir):
        gitdir = join(vcdir, self.metadir())
        # check for existence to also cover git submodules
        return os.path.exists(gitdir)

    def git_command(self, vcdir, args, abortOnError=False, quiet=True):
        args = ['git', '--no-pager'] + args
        if not quiet:
            print('{0}'.format(" ".join(args)))
        out = OutputCapture()
        rc = self.run(args, cwd=vcdir, nonZeroIsFatal=False, out=out)
        if rc in (0, 1):
            return out.data
        else:
            if abortOnError:
                abort(" ".join(args) + ' returned ' + str(rc))
            return None

    def add(self, vcdir, path, abortOnError=True):
        # git add does not support quiet mode, so we capture the output instead ...
        out = OutputCapture()
        return self.run(['git', 'add', path], cwd=vcdir, out=out) == 0

    def commit(self, vcdir, msg, abortOnError=True):
        return self.run(['git', 'commit', '-a', '-m', msg], cwd=vcdir) == 0

    def tip(self, vcdir, abortOnError=True):
        """
        Get the most recent changeset for repo at `vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        self.check_for_git()
        # We don't use run because this can be called very early before _opts is set
        try:
            return _check_output_str(['git', 'rev-list', 'HEAD', '-1'], cwd=vcdir)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git rev-list HEAD failed')
            else:
                return None

    def parent(self, vcdir, abortOnError=True):
        """
        Get the parent changeset of the working directory for repo at `vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        self.check_for_git()
        # We don't use run because this can be called very early before _opts is set
        if exists(join(vcdir, self.metadir(), 'MERGE_HEAD')):
            if abortOnError:
                abort('More than one parent exist during merge')
            return None
        try:
            out = _check_output_str(['git', 'show', '--pretty=format:%H', "-s", 'HEAD'], cwd=vcdir)
            return out.strip()
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git show failed')
            else:
                return None

    def parent_info(self, vcdir, abortOnError=True):
        out = self.git_command(vcdir, ["show", "-s", "--format=%an <%ae>|||%at|||%cn <%ce>|||%ct|||%s", "HEAD"], abortOnError=abortOnError)
        author, author_ts, committer, committer_ts, description = out.split("|||")
        return self._sanitize_parent_info({
            "author": author,
            "author-ts": author_ts,
            "committer": committer,
            "committer-ts": committer_ts,
            "description": description,
        })

    def _tags(self, vcdir, prefix, abortOnError=True):
        """
        Get the list of tags starting with `prefix` in the repository at `vcdir` that are ancestors
        of the current HEAD.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix used to filter the tags
        :param bool abortOnError: if True abort on mx error
        :rtype: list of str
        """
        _tags_prefix = 'tag: '
        try:
            tags_out = _check_output_str(['git', 'log', '--simplify-by-decoration', '--pretty=format:%d', 'HEAD'], cwd=vcdir)
            tags_out = tags_out.strip()
            tags = []
            for line in tags_out.split('\n'):
                line = line.strip()
                if not line:
                    continue
                assert line.startswith('(') and line.endswith(')'), "Unexpected format: " + line
                search = _tags_prefix + prefix
                for decoration in line[1:-1].split(', '):
                    if decoration.startswith(search):
                        tags.append(decoration[len(_tags_prefix):])
            return tags
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('git tag failed: ' + str(e))
            else:
                return None

    def _commitish_revision(self, vcdir, commitish, abortOnError=True):
        """
        Get the commit hash for a commit-ish specifier.

        :param str vcdir: a valid repository path
        :param str commitish: a commit-ish specifier
        :param bool abortOnError: if True abort on mx error
        :rtype: str
        """
        try:
            if not commitish.endswith('^{commit}'):
                commitish += '^{commit}'
            rev = _check_output_str(['git', 'show', '-s', '--format=%H', commitish], cwd=vcdir)
            res = rev.strip()
            assert re.match(r'[0-9a-f]{40}', res) is not None, 'output is not a commit hash: ' + res
            return res
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('git show failed: ' + str(e))
            else:
                return None

    def _latest_revision(self, vcdir, abortOnError=True):
        return self._commitish_revision(vcdir, 'HEAD', abortOnError=abortOnError)

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        """
        Returns a release version derived from VC tags that match the pattern <prefix>-<number>(.<number>)*
        or None if no such tags exist.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix
        :param str snapshotSuffix: the snapshot suffix
        :param bool abortOnError: if True abort on mx error
        :return: a release version
        :rtype: str
        """
        tag_prefix = prefix + '-'
        v_re = re.compile("^" + re.escape(tag_prefix) + r"\d+(?:\.\d+)*$")
        matching_tags = [t for t in self._tags(vcdir, tag_prefix, abortOnError=abortOnError) if v_re.match(t)]
        if matching_tags:
            latest_rev = self._latest_revision(vcdir, abortOnError=abortOnError)
            if latest_rev:
                matching_versions = [[int(x) for x in tag[len(tag_prefix):].split('.')] for tag in matching_tags]
                matching_versions = sorted(matching_versions, reverse=True)
                most_recent_version = matching_versions[0]
                most_recent_tag = tag_prefix + '.'.join((str(x) for x in most_recent_version))
                most_recent_tag_revision = self._commitish_revision(vcdir, most_recent_tag)
                return VC._version_string_helper(latest_rev, most_recent_tag_revision, most_recent_version, snapshotSuffix)
        return None

    def parent_tags(self, vcdir):
        try:
            return _check_output_str(['git', 'tag', '--list', '--points-at', 'HEAD'], cwd=vcdir).strip().split('\r\n')
        except subprocess.CalledProcessError as e:
            abort('git tag failed: ' + str(e))

    @classmethod
    def _head_to_ref(cls, head_name):
        return 'refs/heads/{0}'.format(head_name)

    @classmethod
    def set_branch(cls, vcdir, branch_name, branch_commit='HEAD', with_remote=True):
        """
        Sets branch_name to branch_commit. By using with_remote (the default) the change is
        propagated to origin (but only if the given branch_commit is ahead of its remote
        counterpart (if one exists))
        :param vcdir: the local git repository directory
        :param branch_name: the name the branch should have
        :param branch_commit: the commit_id the branch should point-to
        :param with_remote: if True (default) the change is propagated to origin
        :return: 0 if setting branch was successful
        """
        run(['git', 'branch', '--no-track', '--force', branch_name, branch_commit], cwd=vcdir)
        if not with_remote:
            return 0

        # guaranteed to fail if branch_commit is behind its remote counterpart
        return run(['git', 'push', 'origin', cls._head_to_ref(branch_name)], nonZeroIsFatal=False, cwd=vcdir)

    @classmethod
    def get_matching_branches(cls, repository, brefs, vcdir=None):
        """
        Get dict of branch_name, commit_id entries for branches that match given brefs pattern.
        If vcdir is given then command will be run as if it started in vcdir (allows to use
        git REMOTES for repository).
        :param repository: either URL of git repo or remote that is defined in the local repo
        :param brefs: branch name or branch pattern
        :param vcdir: local repo directory
        :return: dict of branch_name, commit_id entries
        """
        command = ['git']
        if vcdir:
            command += ['-C', vcdir]
        command += ['ls-remote', repository, cls._head_to_ref(brefs)]

        result = dict()
        try:
            head_ref_prefix_length = len(cls._head_to_ref(''))
            for line in _check_output_str(command).splitlines():
                commit_id, branch_name = line.split('\t')
                result[branch_name[head_ref_prefix_length:]] = commit_id
        except subprocess.CalledProcessError:
            pass

        return result

    @classmethod
    def get_branch_remote(cls, remote_url, branch_name):
        """
        Get commit_id that the branch given by remote_url and branch_name points-to.
        :param remote_url: the URL of the git repo that contains the branch
        :param branch_name: the name of the branch whose commit we are interested in
        :return: commit_id the branch points-to or None
        """
        branches = cls.get_matching_branches(remote_url, branch_name)
        if len(branches) != 1:
            return None

        return next(iter(branches.values()))

    def metadir(self):
        return '.git'

    def _local_cache_repo(self):
        cache_path = get_env('MX_GIT_CACHE_DIR') or join(dot_mx_dir(), 'git-cache')
        if not exists(cache_path) or len(os.listdir(cache_path)) == 0:
            self.init(cache_path, bare=True)
        return cache_path

    def _locked_cmd(self, repo, cmd, read_lock=False):
        use_lock = self.object_cache_mode == 'refcache' and flock_cmd() is not None
        if use_lock:
            lock_cmd = [flock_cmd()]
            if read_lock:
                lock_cmd.append("-s")
            lock_cmd.append(join(repo, 'lock'))
            cmd = lock_cmd + cmd
        return cmd

    def _clone(self, url, dest=None, branch=None, rev=None, abortOnError=True, **extra_args):
        hashed_url = hashlib.sha1(_encode(url)).hexdigest()
        cmd = ['git', 'clone']
        if rev and self.object_cache_mode == 'refcache' and GitConfig._is_hash(rev):
            cache = self._local_cache_repo()
            if not self.exists(cache, rev):
                log("Fetch from " + url + " into cache " + cache)
                self._fetch(cache, url, ['+refs/heads/*:refs/remotes/' + hashed_url + '/*'], prune=True, lock=True)
            cmd += ['--no-checkout', '--shared', '--origin', 'cache', '-c', 'gc.auto=0', '-c', 'remote.cache.fetch=+refs/remotes/' + hashed_url + '/*:refs/remotes/cache/*', '-c', 'remote.origin.url=' + url, cache]
        else:
            if branch:
                cmd += ['--branch', branch]
            if self.object_cache_mode:
                cache = self._local_cache_repo()
                log("Fetch from " + url + " into cache " + cache)
                self._fetch(cache, url, '+refs/heads/*:refs/remotes/' + hashed_url + '/*', prune=True, lock=True)
                cmd += ['--reference', cache]
                if self.object_cache_mode == 'dissociated':
                    cmd += ['--dissociate']
            cmd.append(url)
        if dest:
            cmd.append(dest)
        self._log_clone(url, dest, rev)
        out = OutputCapture()
        if self.object_cache_mode:
            cmd = self._locked_cmd(self._local_cache_repo(), cmd, read_lock=True)
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def _reset_rev(self, rev, dest=None, abortOnError=True, **extra_args):
        cmd = ['git']
        cwd = None if dest is None else dest
        cmd.extend(['reset', '--hard', rev])
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, cwd=cwd, out=out)
        logvv(out.data)
        return rc == 0

    hash_re = re.compile(r"^[0-9a-f]{7,40}$")

    @staticmethod
    def _is_hash(rev):
        return rev and bool(GitConfig.hash_re.match(rev))

    def clone(self, url, dest=None, rev='master', abortOnError=True, **extra_args):
        """
        Clone the repo at `url` to `dest` using `rev`

        :param str url: the repository url
        :param str dest: the path to destination, if None the destination is
                         chosen by the vcs
        :param str rev: the desired revision, if None use tip
        :param dict extra_args: for subclass-specific information in/out
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        # TODO: speedup git clone
        # git clone git://source.winehq.org/git/wine.git ~/wine-git --depth 1
        # downsides: This parameter will have the effect of preventing you from
        # cloning it or fetching from it, and other repositories will be unable
        # to push to you, and you won't be able to push to other repositories.
        branch = None if GitConfig._is_hash(rev) else rev
        success = self._clone(url, dest=dest, abortOnError=abortOnError, branch=branch, rev=rev, **extra_args)
        if success and rev and GitConfig._is_hash(rev):
            success = self._reset_rev(rev, dest=dest, abortOnError=abortOnError, **extra_args)
            if not success:
                # TODO: should the cloned repo be removed from disk if the reset op failed?
                log('reset revision failed, removing {0}'.format(dest))
                shutil.rmtree(os.path.abspath(dest))
        return success

    def _fetch(self, vcdir, repository=None, refspec=None, abortOnError=True, prune=False, lock=False):
        try:
            cmd = ['git', 'fetch']
            if prune:
                cmd.append('--prune')
            if repository:
                cmd.append(repository)
            if refspec:
                if isinstance(refspec, list):
                    cmd += refspec
                else:
                    cmd.append(refspec)
            if lock:
                cmd = self._locked_cmd(vcdir, cmd)
            logvv(' '.join(map(pipes.quote, cmd)))
            return subprocess.check_call(cmd, cwd=vcdir)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git fetch failed')
            else:
                return None

    def _log_changes(self, vcdir, path=None, incoming=True, abortOnError=True):
        out = OutputCapture()
        if incoming:
            cmd = ['git', 'log', '..origin/master']
        else:
            cmd = ['git', 'log', 'origin/master..']
        if path:
            cmd.extend(['--', path])
        rc = self.run(cmd, nonZeroIsFatal=False, cwd=vcdir, out=out)
        if rc in (0, 1):
            return out.data
        else:
            if abortOnError:
                abort('{0} returned {1}'.format(
                        'incoming' if incoming else 'outgoing', str(rc)))
            return None

    def active_branch(self, vcdir, abortOnError=True):
        out = OutputCapture()
        cmd = ['git', 'symbolic-ref', '--short', '--quiet', 'HEAD']
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, cwd=vcdir, out=out)
        if rc != 0:
            return None
        else:
            return out.data.rstrip('\r\n')

    def update_to_branch(self, vcdir, branch, abortOnError=True):
        cmd = ['git', 'checkout', branch, '--']
        self.run(cmd, nonZeroIsFatal=abortOnError, cwd=vcdir)

    def incoming(self, vcdir, abortOnError=True):
        """
        list incoming changesets

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository, None if failure and `abortOnError` is False
        :rtype: str
        """
        rc = self._fetch(vcdir, abortOnError=abortOnError)
        if rc == 0:
            return self._log_changes(vcdir, incoming=True, abortOnError=abortOnError)
        else:
            if abortOnError:
                abort('incoming returned ' + str(rc))
            return None

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        """
        llist outgoing changesets to 'dest' or default-push if None

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and `abortOnError` is False
        :rtype: str
        """
        rc = self._fetch(vcdir, abortOnError=abortOnError)
        if rc == 0:
            return self._log_changes(vcdir, path=dest, incoming=False, abortOnError=abortOnError)
        else:
            if abortOnError:
                abort('outgoing returned ' + str(rc))
            return None

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        """
        Pull a given changeset (the head if `rev` is None), optionally updating
        the working directory. Updating is only done if something was pulled.
        If there were no new changesets or `rev` was already known locally,
        no update is performed.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision, if None use tip
        :param bool abortOnError: if True abort on mx error
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        if update and not rev:
            cmd = ['git', 'pull']
            self._log_pull(vcdir, rev)
            out = OutputCapture()
            rc = self.run(cmd, nonZeroIsFatal=abortOnError, cwd=vcdir, out=out)
            logvv(out.data)
            return rc == 0
        else:
            rc = self._fetch(vcdir, abortOnError=abortOnError)
            if rc == 0:
                if rev and update:
                    return self.update(vcdir, rev=rev, mayPull=False, clean=False, abortOnError=abortOnError)
            else:
                if abortOnError:
                    abort('fetch returned ' + str(rc))
                return False

    def can_push(self, vcdir, strict=True, abortOnError=True):
        """
        Check if `vcdir` can be pushed.

        :param str vcdir: a valid repository path
        :param bool strict: if set no uncommitted changes or unadded are allowed
        :return: True if we can push, False otherwise
        :rtype: bool
        """
        out = OutputCapture()
        rc = self.run(['git', 'status', '--porcelain'], cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            if strict:
                return output == ''
            else:
                if len(output) > 0:
                    for line in output.split('\n'):
                        if len(line) > 0 and not line.startswith('??'):
                            return False
                return True
        else:
            return False

    def _branch_remote(self, vcdir, branch, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['git', 'config', '--get', 'branch.' + branch + '.remote'], cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            return out.data.rstrip('\r\n')
        assert not abortOnError
        return None

    def _remote_url(self, vcdir, remote, push=False, abortOnError=True):
        if is_windows():
            cmd = ['git', 'ls-remote', '--get-url']
        else:
            cmd = ['git', 'remote', 'get-url']
            if push:
                cmd += ['--push']
        cmd += [remote]
        out = OutputCapture()
        rc = self.run(cmd, cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            return out.data.rstrip('\r\n')
        assert not abortOnError
        return None

    def _path(self, vcdir, name, abortOnError=True):
        branch = self.active_branch(vcdir, abortOnError=False)
        if not branch:
            branch = 'master'

        remote = self._branch_remote(vcdir, branch, abortOnError=False)
        if not remote and branch != 'master':
            remote = self._branch_remote(vcdir, 'master', abortOnError=False)
        if not remote:
            remote = 'origin'
        return self._remote_url(vcdir, remote, name == 'push', abortOnError=abortOnError)

    def default_push(self, vcdir, abortOnError=True):
        """
        get the default push target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default push target for repo
        :rtype: str
        """
        push = self._path(vcdir, 'push', abortOnError=False)
        if push:
            return push
        return self.default_pull(vcdir, abortOnError=abortOnError)

    def default_pull(self, vcdir, abortOnError=True):
        """
        get the default pull target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default pull target for repo
        :rtype: str
        """
        return self._path(vcdir, 'fetch', abortOnError=abortOnError)

    def push(self, vcdir, dest=None, rev=None, abortOnError=False):
        """
        Push `vcdir` at rev `rev` to default if `dest`
        is None, else push to `dest`.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param str dest: the path to destination
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        cmd = ['git', 'push']
        cmd.append(dest if dest else 'origin')
        cmd.append('{0}master'.format('{0}:'.format(rev) if rev else ''))
        self._log_push(vcdir, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        """
        update the `vcdir` working directory.
        If `rev` is not specified, update to the tip of the current branch.
        If `rev` is specified, `mayPull` controls whether a pull will be attempted if
        `rev` can not be found locally.
        If `clean` is True, uncommitted changes will be discarded (no backup!).

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param bool mayPull: flag to controll whether to pull or not
        :param bool clean: discard uncommitted changes without backing up
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        if rev and mayPull and not self.exists(vcdir, rev):
            self.pull(vcdir, rev=rev, update=False, abortOnError=abortOnError)
            if not self.exists(vcdir, rev):
                abort('Fetch of %s succeeded\nbut did not contain requested revision %s.\nCheck that the suite.py repository location is mentioned by \'git remote -v\'' % (vcdir, rev))
        cmd = ['git', 'checkout']
        if clean:
            cmd.append('-f')
        if rev:
            cmd.extend(['--detach', rev])
            if not _opts.verbose:
                cmd.append('-q')
        else:
            cmd.extend(['master', '--'])
        return self.run(cmd, cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def locate(self, vcdir, patterns=None, abortOnError=True):
        """
        Return a list of paths under vc control that match `patterns`

        :param str vcdir: a valid repository path
        :param patterns: a list of patterns
        :type patterns: str or list or None
        :param bool abortOnError: if True abort on mx error
        :return: a list of paths under vc control
        :rtype: list
        """
        if patterns is None:
            patterns = []
        elif not isinstance(patterns, list):
            patterns = [patterns]
        out = LinesOutputCapture()
        err = OutputCapture()
        rc = self.run(['git', 'ls-files'] + patterns, cwd=vcdir, out=out, err=err, nonZeroIsFatal=False)
        if rc == 0:
            return out.lines
        else:
            if abortOnError:
                abort('locate returned: {}\n{}'.format(rc, out.data))
            else:
                return None

    def isDirty(self, vcdir, abortOnError=True):
        """
        check whether the working directory is dirty

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True of the working directory is dirty, False otherwise
        :rtype: bool
        """
        self.check_for_git()
        try:
            output = _check_output_str(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=vcdir)
            return len(output.strip()) > 0
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get status')
            else:
                return None

    def status(self, vcdir, abortOnError=True):
        """
        report the status of the repository

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        return run(['git', 'status'], cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        """
        Place a bookmark at a given revision

        :param str vcdir: a valid repository path
        :param str name: the name of the bookmark
        :param str rev: the desired revision
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        return run(['git', 'branch', '-f', name, rev], cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        """
        Returns the latest of 2 revisions (in chronological order).
        The revisions should be related in the DAG.

        :param str vcdir: a valid repository path
        :param str rev1: the first revision
        :param str rev2: the second revision
        :param bool abortOnError: if True abort on mx error
        :return: the latest of the 2 revisions
        :rtype: str or None
        """
        self.check_for_git()
        try:
            out = _check_output_str(['git', 'rev-list', '-n', '1', '--date-order', rev1, rev2], cwd=vcdir)
            changesets = out.strip().split('\n')
            if len(changesets) != 1:
                if abortOnError:
                    abort('git rev-list returned {0} possible latest (expected 1)'.format(len(changesets)))
                return None
            return changesets[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('latest failed')
            else:
                return None

    def exists(self, vcdir, rev):
        """
        Check if a given revision exists in the repository.

        :param str vcdir: a valid repository path
        :param str rev: the second revision
        :return: True if revision exists, False otherwise
        :rtype: bool
        """
        self.check_for_git()
        try:
            _check_output_str(['git', 'cat-file', '-e', rev], cwd=vcdir)
            return True
        except subprocess.CalledProcessError:
            return False

    def root(self, directory, abortOnError=True):
        if VC._find_metadata_dir(directory, '.git'):
            if self.check_for_git(abortOnError=abortOnError):
                try:
                    out = _check_output_str(['git', 'rev-parse', '--show-toplevel'], cwd=directory, stderr=subprocess.STDOUT)
                    return out.strip()
                except subprocess.CalledProcessError:
                    if abortOnError:
                        abort('`git rev-parse --show-toplevel` (root) failed')
        elif abortOnError:
            abort('No .git directory')
        return None


class BinaryVC(VC):
    """
    Emulates a VC system for binary suites, as far as possible, but particularly pull/tip
    """
    def __init__(self):
        VC.__init__(self, 'binary', 'MX Binary')

    def check(self, abortOnError=True):
        return True

    def is_this_vc(self, vcdir):
        try:
            return self.parent(vcdir, abortOnError=False)
        except IOError:
            return False

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        """
        Downloads the ``mx-suitename.jar`` file. The caller is responsible for downloading
        the suite distributions. The actual version downloaded is written to the file
        ``mx-suitename.jar.<version>``.

        :param extra_args: Additional args that must include `suite_name` which is a string
              denoting the suite name and `result` which is a dict for output values. If this
              method returns True, then there will be a `adj_version` entry in this dict
              containing the actual (adjusted) version
        :return: True if the clone was successful, False otherwise
        :rtype: bool
        """
        assert dest
        suite_name = extra_args['suite_name']
        metadata = self.Metadata(suite_name, url, None, None)
        if not rev:
            rev = self._tip(metadata)
        metadata.snapshotVersion = '{0}-SNAPSHOT'.format(rev)

        mxname = _mx_binary_distribution_root(suite_name)
        self._log_clone("{}/{}/{}".format(url, _mavenGroupId(suite_name).replace('.', '/'), mxname), dest, rev)
        mx_jar_path = join(dest, _mx_binary_distribution_jar(suite_name))
        if not self._pull_artifact(metadata, _mavenGroupId(suite_name), mxname, mxname, mx_jar_path, abortOnVersionError=abortOnError):
            return False
        run([get_jdk(tag=DEFAULT_JDK_TAG).jar, 'xf', mx_jar_path], cwd=dest)
        self._writeMetadata(dest, metadata)
        return True

    def _pull_artifact(self, metadata, groupId, artifactId, name, path, sourcePath=None, abortOnVersionError=True, extension='jar'):
        repo = MavenRepo(metadata.repourl)
        snapshot = repo.getSnapshot(groupId, artifactId, metadata.snapshotVersion)
        if not snapshot:
            if abortOnVersionError:
                url = repo.getSnapshotUrl(groupId, artifactId, metadata.snapshotVersion)
                abort('Version {} not found for {}:{} ({})'.format(metadata.snapshotVersion, groupId, artifactId, url))
            return False
        build = snapshot.getCurrentSnapshotBuild()
        metadata.snapshotTimestamp = snapshot.currentTime
        try:
            (jar_url, jar_sha_url) = build.getSubArtifact(extension)
        except MavenSnapshotArtifact.NonUniqueSubArtifactException:
            raise abort('Multiple {}s found for {} in snapshot {} in repository {}'.format(extension, name, build.version, repo.repourl))
        download_file_with_sha1(artifactId, path, [jar_url], _hashFromUrl(jar_sha_url), path + '.sha1', resolve=True, mustExist=True, sources=False)
        if sourcePath:
            try:
                (source_url, source_sha_url) = build.getSubArtifactByClassifier('sources')
            except MavenSnapshotArtifact.NonUniqueSubArtifactException:
                raise abort('Multiple source artifacts found for {} in snapshot {} in repository {}'.format(name, build.version, repo.repourl))
            download_file_with_sha1(artifactId + '_sources', sourcePath, [source_url], _hashFromUrl(source_sha_url), sourcePath + '.sha1', resolve=True, mustExist=True, sources=True)
        return True

    class Metadata:
        def __init__(self, suiteName, repourl, snapshotVersion, snapshotTimestamp):
            self.suiteName = suiteName
            self.repourl = repourl
            self.snapshotVersion = snapshotVersion
            self.snapshotTimestamp = snapshotTimestamp

    def _writeMetadata(self, vcdir, metadata):
        with open(join(vcdir, _mx_binary_distribution_version(metadata.suiteName)), 'w') as f:
            f.write("{0},{1},{2}".format(metadata.repourl, metadata.snapshotVersion, metadata.snapshotTimestamp))

    def _readMetadata(self, vcdir):
        suiteName = basename(vcdir)
        with open(join(vcdir, _mx_binary_distribution_version(suiteName))) as f:
            parts = f.read().split(',')
            if len(parts) == 2:
                # Older versions of the persisted metadata do not contain the snapshot timestamp.
                repourl, snapshotVersion = parts
                snapshotTimestamp = None
            else:
                repourl, snapshotVersion, snapshotTimestamp = parts
        return self.Metadata(suiteName, repourl, snapshotVersion, snapshotTimestamp)

    def getDistribution(self, vcdir, distribution):
        suiteName = basename(vcdir)
        reason = distribution.needsUpdate(TimeStampFile(join(vcdir, _mx_binary_distribution_version(suiteName)), followSymlinks=False))
        if not reason:
            return
        log('Updating {} [{}]'.format(distribution, reason))
        metadata = self._readMetadata(vcdir)
        artifactId = distribution.maven_artifact_id()
        groupId = distribution.maven_group_id()
        path = distribution.path[:-len(distribution.localExtension())] + distribution.remoteExtension()
        if distribution.isJARDistribution():
            sourcesPath = distribution.sourcesPath
        else:
            sourcesPath = None
        with SafeFileCreation(path, companion_patterns=["{path}.sha1"]) as sfc, SafeFileCreation(sourcesPath, companion_patterns=["{path}.sha1"]) as sourceSfc:
            self._pull_artifact(metadata, groupId, artifactId, distribution.remoteName(), sfc.tmpPath, sourcePath=sourceSfc.tmpPath, extension=distribution.remoteExtension())
            final_path = distribution.postPull(sfc.tmpPath)
        if final_path:
            os.rename(final_path, distribution.path)
        assert exists(distribution.path)
        distribution.notify_updated()

    def pull(self, vcdir, rev=None, update=True, abortOnError=True):
        if not update:
            return False  # TODO or True?

        metadata = self._readMetadata(vcdir)
        if not rev:
            rev = self._tip(metadata)
        if rev == self._id(metadata):
            return False

        metadata.snapshotVersion = '{0}-SNAPSHOT'.format(rev)
        tmpdir = tempfile.mkdtemp()
        mxname = _mx_binary_distribution_root(metadata.suiteName)
        tmpmxjar = join(tmpdir, mxname + '.jar')
        if not self._pull_artifact(metadata, _mavenGroupId(metadata.suiteName), mxname, mxname, tmpmxjar, abortOnVersionError=abortOnError):
            shutil.rmtree(tmpdir)
            return False

        # pull the new version and update 'working directory'
        # i.e. delete first as everything will change
        shutil.rmtree(vcdir)

        mx_jar_path = join(vcdir, _mx_binary_distribution_jar(metadata.suiteName))
        ensure_dir_exists(dirname(mx_jar_path))

        shutil.copy2(tmpmxjar, mx_jar_path)
        shutil.rmtree(tmpdir)
        run([get_jdk(tag=DEFAULT_JDK_TAG).jar, 'xf', mx_jar_path], cwd=vcdir)

        self._writeMetadata(vcdir, metadata)
        return True

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        return self.pull(vcdir=vcdir, rev=rev, update=True, abortOnError=abortOnError)

    def tip(self, vcdir, abortOnError=True):
        self._tip(self._readMetadata(vcdir))

    def _tip(self, metadata):
        repo = MavenRepo(metadata.repourl)
        warn("Using `tip` on a binary suite is unreliable.")
        latestSnapshotversion = repo.getArtifactVersions(_mavenGroupId(metadata.suiteName), _mx_binary_distribution_root(metadata.suiteName)).latestVersion
        assert latestSnapshotversion.endswith('-SNAPSHOT')
        return latestSnapshotversion[:-len('-SNAPSHOT')]

    def default_pull(self, vcdir, abortOnError=True):
        return self._readMetadata(vcdir).repourl

    def parent(self, vcdir, abortOnError=True):
        return self._id(self._readMetadata(vcdir))

    def parent_info(self, vcdir, abortOnError=True):
        def decode(ts):
            if ts is None:
                return 0
            yyyy = int(ts[0:4])
            mm = int(ts[4:6])
            dd = int(ts[6:8])
            hh = int(ts[9:11])
            mi = int(ts[11:13])
            ss = int(ts[13:15])
            return (datetime(yyyy, mm, dd, hh, mi, ss) - datetime(1970, 1, 1)).total_seconds()
        metadata = self._readMetadata(vcdir)
        timestamp = decode(metadata.snapshotTimestamp)
        return {
            "author": "<unknown>",
            "author-ts": timestamp,
            "committer": "<unknown>",
            "committer-ts": timestamp,
        }

    def _id(self, metadata):
        assert metadata.snapshotVersion.endswith('-SNAPSHOT')
        return metadata.snapshotVersion[:-len('-SNAPSHOT')]

    def isDirty(self, abortOnError=True):
        # a binary repo can not be dirty
        return False

    def status(self, abortOnError=True):
        # a binary repo has nothing to report
        return True

    def root(self, directory, abortOnError=True):
        if abortOnError:
            abort("A binary VC has no 'root'")

    def active_branch(self, vcdir, abortOnError=True):
        if abortOnError:
            abort("A binary VC has no active branch")

    def update_to_branch(self, vcdir, branch, abortOnError=True):
        if abortOnError:
            abort("A binary VC has no branch")


### Maven, _private

def _map_to_maven_dist_name(name):
    return name.lower().replace('_', '-')


class MavenArtifactVersions:
    def __init__(self, latestVersion, releaseVersion, versions):
        self.latestVersion = latestVersion
        self.releaseVersion = releaseVersion
        self.versions = versions


class MavenSnapshotBuilds:
    def __init__(self, currentTime, currentBuildNumber, snapshots):
        self.currentTime = currentTime
        self.currentBuildNumber = currentBuildNumber
        self.snapshots = snapshots

    def getCurrentSnapshotBuild(self):
        return self.snapshots[(self.currentTime, self.currentBuildNumber)]


class MavenSnapshotArtifact:
    def __init__(self, groupId, artifactId, version, snapshotBuildVersion, repo):
        self.groupId = groupId
        self.artifactId = artifactId
        self.version = version
        self.snapshotBuildVersion = snapshotBuildVersion
        self.subArtifacts = []
        self.repo = repo

    class SubArtifact:
        def __init__(self, extension, classifier):
            self.extension = extension
            self.classifier = classifier

        def __repr__(self):
            return str(self)

        def __str__(self):
            return "{0}.{1}".format(self.classifier, self.extension) if self.classifier else self.extension

    def addSubArtifact(self, extension, classifier):
        self.subArtifacts.append(self.SubArtifact(extension, classifier))

    class NonUniqueSubArtifactException(Exception):
        pass

    def _getUniqueSubArtifact(self, criterion):
        filtered = [sub for sub in self.subArtifacts if criterion(sub.extension, sub.classifier)]
        if len(filtered) == 0:
            return None
        if len(filtered) > 1:
            raise self.NonUniqueSubArtifactException()
        sub = filtered[0]
        if sub.classifier:
            url = "{url}/{group}/{artifact}/{version}/{artifact}-{snapshotBuildVersion}-{classifier}.{extension}".format(
                url=self.repo.repourl,
                group=self.groupId.replace('.', '/'),
                artifact=self.artifactId,
                version=self.version,
                snapshotBuildVersion=self.snapshotBuildVersion,
                classifier=sub.classifier,
                extension=sub.extension)
        else:
            url = "{url}/{group}/{artifact}/{version}/{artifact}-{snapshotBuildVersion}.{extension}".format(
                url=self.repo.repourl,
                group=self.groupId.replace('.', '/'),
                artifact=self.artifactId,
                version=self.version,
                snapshotBuildVersion=self.snapshotBuildVersion,
                extension=sub.extension)
        return url, url + '.sha1'

    def getSubArtifact(self, extension, classifier=None):
        return self._getUniqueSubArtifact(lambda e, c: e == extension and c == classifier)

    def getSubArtifactByClassifier(self, classifier):
        return self._getUniqueSubArtifact(lambda e, c: c == classifier)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "{0}:{1}:{2}-SNAPSHOT".format(self.groupId, self.artifactId, self.snapshotBuildVersion)


class MavenRepo:
    def __init__(self, repourl):
        self.repourl = repourl
        self.artifactDescs = {}

    def getArtifactVersions(self, groupId, artifactId):
        metadataUrl = "{0}/{1}/{2}/maven-metadata.xml".format(self.repourl, groupId.replace('.', '/'), artifactId)
        logv('Retrieving and parsing {0}'.format(metadataUrl))
        try:
            metadataFile = _urlopen(metadataUrl, timeout=10)
        except _urllib_error.HTTPError as e:
            _suggest_http_proxy_error(e)
            abort('Error while retrieving metadata for {}:{}: {}'.format(groupId, artifactId, str(e)))
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId

            versioning = root.find('versioning')
            latest = versioning.find('latest')
            release = versioning.find('release')
            versions = versioning.find('versions')
            versionStrings = [v.text for v in versions.iter('version')]
            releaseVersionString = release.text if release is not None and len(release) != 0 else None
            if latest is not None and len(latest) != 0:
                latestVersionString = latest.text
            else:
                logv('Element \'latest\' not specified in metadata. Fallback: Find latest via \'versions\'.')
                latestVersionString = None
                for version_str in reversed(versionStrings):
                    snapshot_metadataUrl = self.getSnapshotUrl(groupId, artifactId, version_str)
                    try:
                        snapshot_metadataFile = _urlopen(snapshot_metadataUrl, timeout=10)
                    except _urllib_error.HTTPError as e:
                        logv('Version {0} not accessible. Try previous snapshot.'.format(metadataUrl))
                        snapshot_metadataFile = None

                    if snapshot_metadataFile:
                        logv('Using version {0} as latestVersionString.'.format(version_str))
                        latestVersionString = version_str
                        snapshot_metadataFile.close()
                        break

            return MavenArtifactVersions(latestVersionString, releaseVersionString, versionStrings)
        except _urllib_error.URLError as e:
            abort('Error while retrieving versions for {0}:{1}: {2}'.format(groupId, artifactId, str(e)))
        finally:
            if metadataFile:
                metadataFile.close()

    def getSnapshotUrl(self, groupId, artifactId, version):
        return "{0}/{1}/{2}/{3}/maven-metadata.xml".format(self.repourl, groupId.replace('.', '/'), artifactId, version)

    def getSnapshot(self, groupId, artifactId, version):
        assert version.endswith('-SNAPSHOT')
        metadataUrl = self.getSnapshotUrl(groupId, artifactId, version)
        logv('Retrieving and parsing {0}'.format(metadataUrl))
        try:
            metadataFile = _urlopen(metadataUrl, timeout=10)
        except _urllib_error.URLError as e:
            if isinstance(e, _urllib_error.HTTPError) and e.code == 404:
                return None
            _suggest_http_proxy_error(e)
            abort('Error while retrieving snapshot for {}:{}:{}: {}'.format(groupId, artifactId, version, str(e)))
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId
            assert root.find('version').text == version

            versioning = root.find('versioning')
            snapshot = versioning.find('snapshot')
            snapshotVersions = versioning.find('snapshotVersions')
            currentSnapshotTime = snapshot.find('timestamp').text
            currentSnapshotBuildElement = snapshot.find('buildNumber')
            currentSnapshotBuildNumber = int(currentSnapshotBuildElement.text) if currentSnapshotBuildElement is not None else 0

            versionPrefix = version[:-len('-SNAPSHOT')] + '-'
            prefixLen = len(versionPrefix)
            snapshots = {}
            for snapshotVersion in snapshotVersions.iter('snapshotVersion'):
                fullVersion = snapshotVersion.find('value').text
                separatorIndex = fullVersion.index('-', prefixLen)
                timeStamp = fullVersion[prefixLen:separatorIndex]
                buildNumber = int(fullVersion[separatorIndex+1:])
                extension = snapshotVersion.find('extension').text
                classifier = snapshotVersion.find('classifier')
                classifierString = None
                if classifier is not None and len(classifier.text) > 0:
                    classifierString = classifier.text
                artifact = snapshots.setdefault((timeStamp, buildNumber), MavenSnapshotArtifact(groupId, artifactId, version, fullVersion, self))

                artifact.addSubArtifact(extension, classifierString)
            return MavenSnapshotBuilds(currentSnapshotTime, currentSnapshotBuildNumber, snapshots)
        finally:
            if metadataFile:
                metadataFile.close()


_maven_local_repository = None


def maven_local_repository():  # pylint: disable=invalid-name
    global _maven_local_repository

    if not _maven_local_repository:
        class _MavenLocalRepository(Repository):
            """This singleton class represents mavens local repository (usually under ~/.m2/repository)"""
            def __init__(self):
                try:
                    res = {'lines': '', 'xml': False}
                    def xml_settings_grabber(line):
                        if not res['xml'] and not res['lines'] and line.startswith('<settings '):
                            res['xml'] = True
                        if res['xml']:
                            res['lines'] += line
                            if line.startswith('</settings>'):
                                res['xml'] = False
                    run_maven(['help:effective-settings'], out=xml_settings_grabber)
                    dom = minidomParseString(res['lines'])
                    local_repo = dom.getElementsByTagName('localRepository')[0].firstChild.data
                    url = 'file://' + local_repo
                except:
                    raise abort('Unable to determine maven local repository URL')
                Repository.__init__(self, suite('mx'), 'maven local repository', url, url, [])

            def resolveLicenses(self):
                return True

        _maven_local_repository = _MavenLocalRepository()

    return _maven_local_repository


### ~~~~~~~~~~~~~ Maven, _private

def _mavenGroupId(suite):
    if isinstance(suite, Suite):
        group_id = suite._get_early_suite_dict_property('groupId')
        if group_id:
            return group_id
        name = suite.name
    else:
        assert isinstance(suite, str)
        name = suite
    return 'com.oracle.' + _map_to_maven_dist_name(name)


def _genPom(dist, versionGetter, validateMetadata='none'):
    """
    :type dist: Distribution
    """
    groupId = dist.maven_group_id()
    artifactId = dist.maven_artifact_id()
    version = versionGetter(dist.suite)
    pom = XMLDoc()
    pom.open('project', attributes={
        'xmlns': "http://maven.apache.org/POM/4.0.0",
        'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'xsi:schemaLocation': "http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"
        })
    pom.element('modelVersion', data="4.0.0")
    pom.element('groupId', data=groupId)
    pom.element('artifactId', data=artifactId)
    pom.element('version', data=version)
    if dist.remoteExtension() != 'jar':
        pom.element('packaging', data=dist.remoteExtension())
    if dist.suite.url:
        pom.element('url', data=dist.suite.url)
    elif validateMetadata != 'none':
        if 'suite-url' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            abort("Suite {} is missing the 'url' attribute".format(dist.suite.name))
        warn("Suite {}'s  version is too old to contain the 'url' attribute".format(dist.suite.name))
    acronyms = ['API', 'DSL', 'SL', 'TCK']
    name = ' '.join((t if t in acronyms else t.lower().capitalize() for t in dist.name.split('_')))
    pom.element('name', data=name)
    if hasattr(dist, 'description'):
        pom.element('description', data=dist.description)
    elif validateMetadata != 'none':
        if 'dist-description' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            dist.abort("Distribution is missing the 'description' attribute")
        dist.warn("Distribution's suite version is too old to have the 'description' attribute")
    if dist.suite.developer:
        pom.open('developers')
        pom.open('developer')
        def _addDevAttr(name, default=None):
            if name in dist.suite.developer:
                value = dist.suite.developer[name]
            else:
                value = default
            if value:
                pom.element(name, data=value)
            elif validateMetadata != 'none':
                abort("Suite {}'s developer metadata is missing the '{}' attribute".format(dist.suite.name, name))
        _addDevAttr('name')
        _addDevAttr('email')
        _addDevAttr('organization')
        _addDevAttr('organizationUrl', dist.suite.url)
        pom.close('developer')
        pom.close('developers')
    elif validateMetadata != 'none':
        if 'suite-developer' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            abort("Suite {} is missing the 'developer' attribute".format(dist.suite.name))
        warn("Suite {}'s version is too old to contain the 'developer' attribute".format(dist.suite.name))
    if dist.theLicense:
        pom.open('licenses')
        for distLicense in dist.theLicense:
            pom.open('license')
            pom.element('name', data=distLicense.fullname)
            pom.element('url', data=distLicense.url)
            pom.close('license')
        pom.close('licenses')
    elif validateMetadata != 'none':
        if dist.suite.getMxCompatibility().supportsLicenses() or validateMetadata == 'full':
            dist.abort("Distribution is missing 'license' attribute")
        dist.warn("Distribution's suite version is too old to have the 'license' attribute")
    directDistDeps = [d for d in dist.deps if d.isDistribution()]
    directLibDeps = dist.excludedLibs
    if directDistDeps or directLibDeps:
        pom.open('dependencies')
        for dep in directDistDeps:
            if dep.suite.internal:
                warn("_genPom({}): ignoring internal dependency {}".format(dist, dep))
                continue
            if validateMetadata != 'none' and not getattr(dep, 'maven', False):
                if validateMetadata == 'full':
                    dist.abort("Distribution depends on non-maven distribution {}".format(dep))
                dist.warn("Distribution depends on non-maven distribution {}".format(dep))
            for platform in dep.platforms:
                pom.open('dependency')
                pom.element('groupId', data=dep.maven_group_id())
                pom.element('artifactId', data=dep.maven_artifact_id(platform=platform))
                dep_version = versionGetter(dep.suite)
                if validateMetadata != 'none' and 'SNAPSHOT' in dep_version and 'SNAPSHOT' not in version:
                    if validateMetadata == 'full':
                        dist.abort("non-snapshot distribution depends on snapshot distribution {}".format(dep))
                    dist.warn("non-snapshot distribution depends on snapshot distribution {}".format(dep))
                pom.element('version', data=dep_version)
                if dep.remoteExtension() != 'jar':
                    pom.element('type', data=dep.remoteExtension())
                pom.close('dependency')
        for l in directLibDeps:
            if (l.isJdkLibrary() or l.isJreLibrary()) and l.is_provided_by(get_jdk()) and l.is_provided_by(get_jdk(dist.maxJavaCompliance())):
                continue
            if hasattr(l, 'maven'):
                mavenMetaData = l.maven
                pom.open('dependency')
                pom.element('groupId', data=mavenMetaData['groupId'])
                pom.element('artifactId', data=mavenMetaData['artifactId'])
                pom.element('version', data=mavenMetaData['version'])
                if dist.suite.getMxCompatibility().mavenSupportsClassifier():
                    if 'suffix' in mavenMetaData:
                        l.abort('The use of "suffix" as maven metadata is not supported in this version. Use "classifier" instead.')
                    if 'classifier' in mavenMetaData:
                        pom.element('classifier', data=mavenMetaData['classifier'])
                else:
                    if 'suffix' in mavenMetaData:
                        pom.element('classifier', data=mavenMetaData['suffix'])
                pom.close('dependency')
            elif validateMetadata != 'none':
                if 'library-coordinates' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
                    l.abort("Library is missing maven metadata")
                l.warn("Library's suite version is too old to have maven metadata")
        pom.close('dependencies')
    pom.open('scm')
    scm = dist.suite.scm_metadata(abortOnError=validateMetadata != 'none')
    pom.element('connection', data='scm:{}:{}'.format(dist.suite.vc.kind, scm.read))
    if scm.read != scm.write or validateMetadata == 'full':
        pom.element('developerConnection', data='scm:{}:{}'.format(dist.suite.vc.kind, scm.write))
    pom.element('url', data=scm.url)
    pom.close('scm')
    pom.close('project')
    return pom.xml(indent='  ', newl='\n')


def _tmpPomFile(dist, versionGetter, validateMetadata='none'):
    tmp = tempfile.NamedTemporaryFile('w', suffix='.pom', delete=False)
    tmp.write(_genPom(dist, versionGetter, validateMetadata))
    tmp.close()
    return tmp.name


def _deploy_binary_maven(suite, artifactId, groupId, filePath, version, repo,
                         srcPath=None,
                         description=None,
                         settingsXml=None,
                         extension='jar',
                         dryRun=False,
                         pomFile=None,
                         gpg=False,
                         keyid=None,
                         javadocPath=None,
                         extraFiles=None):
    """
    :type extraFiles: list[(str, str, str)]
    """
    assert exists(filePath)
    assert not srcPath or exists(srcPath)

    cmd = ['--batch-mode']

    if not _opts.verbose:
        cmd.append('--quiet')

    if _opts.verbose:
        cmd.append('--errors')

    if _opts.very_verbose:
        cmd.append('--debug')

    if settingsXml:
        cmd += ['-s', settingsXml]

    if repo != maven_local_repository():
        cmd += [
            '-DrepositoryId=' + repo.name,
            '-Durl=' + repo.get_url(version)
        ]
        if gpg:
            cmd += ['gpg:sign-and-deploy-file']
        else:
            cmd += ['deploy:deploy-file']
        if keyid:
            cmd += ['-Dgpg.keyname=' + keyid]
    else:
        cmd += ['install:install-file']
        if gpg or keyid:
            abort('Artifact signing not supported for ' + repo.name)

    cmd += [
        '-DgroupId=' + groupId,
        '-DartifactId=' + artifactId,
        '-Dversion=' + version,
        '-Dfile=' + filePath,
        '-Dpackaging=' + extension,
        '-DretryFailedDeploymentCount=10'
    ]
    if pomFile:
        cmd.append('-DpomFile=' + pomFile)
    else:
        cmd.append('-DgeneratePom=true')

    if srcPath:
        cmd.append('-Dsources=' + srcPath)
    if javadocPath:
        cmd.append('-Djavadoc=' + javadocPath)

    if description:
        cmd.append('-Ddescription=' + description)

    if extraFiles:
        cmd.append('-Dfiles=' + ','.join(ef[0] for ef in extraFiles))
        cmd.append('-Dclassifiers=' + ','.join(ef[1] for ef in extraFiles))
        cmd.append('-Dtypes=' + ','.join(ef[2] for ef in extraFiles))

    action = 'Installing' if repo == maven_local_repository() else 'Deploying'
    log('{} {}:{}...'.format(action, groupId, artifactId))
    if dryRun:
        logv(' '.join((pipes.quote(t) for t in cmd)))
    else:
        run_maven(cmd)


def _deploy_skip_existing(args, dists, version, repo):
    if args.skip_existing:
        non_existing_dists = []
        for dist in dists:
            if version.endswith('-SNAPSHOT'):
                metadata_append = '-local' if repo == maven_local_repository() else ''
                metadata_url = '{0}/{1}/{2}/{3}/maven-metadata{4}.xml'.format(repo.get_url(version), dist.maven_group_id().replace('.', '/'), dist.maven_artifact_id(), version, metadata_append)
            else:
                metadata_url = '{0}/{1}/{2}/{3}/'.format(repo.get_url(version), dist.maven_group_id().replace('.', '/'), dist.maven_artifact_id(), version)
            if download_file_exists([metadata_url]):
                log('Skip existing {}:{}'.format(dist.maven_group_id(), dist.maven_artifact_id()))
            else:
                non_existing_dists.append(dist)
        return non_existing_dists
    else:
        return dists


def deploy_binary(args):
    """deploy binaries for the primary suite to remote maven repository

    All binaries must be built first using ``mx build``.
    """
    parser = ArgumentParser(prog='mx deploy-binary')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--only', action='store', help='Limit deployment to these distributions')
    parser.add_argument('--platform-dependent', action='store_true', help='Limit deployment to platform dependent distributions only')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    parser.add_argument('--skip-existing', action='store_true', help='Do not deploy distributions if already in repository')
    parser.add_argument('repository_id', metavar='repository-id', nargs='?', action='store', help='Repository ID used for binary deploy. If none is given, mavens local repository is used instead.')
    parser.add_argument('url', metavar='repository-url', nargs='?', action='store', help='Repository URL used for binary deploy. If no url is given, the repository-id is looked up in suite.py')
    args = parser.parse_args(args)

    if args.all_suites:
        _suites = suites()
    else:
        _suites = primary_or_specific_suites()

    for s in _suites:
        if s.isSourceSuite():
            _deploy_binary(args, s)


def _deploy_binary(args, suite):
    if not suite.getMxCompatibility().supportsLicenses():
        log("Not deploying '{0}' because licenses aren't defined".format(suite.name))
        return
    if not suite.getMxCompatibility().supportsRepositories():
        log("Not deploying '{0}' because repositories aren't defined".format(suite.name))
        return
    if not suite.vc:
        abort('Current suite has no version control')

    _mvn.check()
    def versionGetter(suite):
        return '{0}-SNAPSHOT'.format(suite.vc.parent(suite.vc_dir))
    dists = suite.dists
    if args.only:
        only = args.only.split(',')
        dists = [d for d in dists if d.name in only or d.qualifiedName() in only]
    if args.platform_dependent:
        dists = [d for d in dists if d.platformDependent]

    mxMetaName = _mx_binary_distribution_root(suite.name)
    suite.create_mx_binary_distribution_jar()
    mxMetaJar = suite.mx_binary_distribution_jar_path()
    assert exists(mxMetaJar)
    if args.all_suites:
        dists = [d for d in dists if d.exists()]

    for dist in dists:
        if not dist.exists():
            abort("'{0}' is not built, run 'mx build' first".format(dist.name))

    platform_dependence = any(d.platformDependent for d in dists)

    if args.url:
        repo = Repository(None, args.repository_id, args.url, args.url, repository(args.repository_id).licenses)
    elif args.repository_id:
        if not suite.getMxCompatibility().supportsRepositories():
            abort("Repositories are not supported in {}'s suite version".format(suite.name))
        repo = repository(args.repository_id)
    else:
        repo = maven_local_repository()

    version = versionGetter(suite)
    if not args.only:
        action = 'Installing' if repo == maven_local_repository() else 'Deploying'
        log('{} suite {} version {}'.format(action, suite.name, version))
    dists = _deploy_skip_existing(args, dists, version, repo)
    if not dists:
        return

    _maven_deploy_dists(dists, versionGetter, repo, args.settings, dryRun=args.dry_run, deployMapFiles=True)
    if not args.platform_dependent and not args.only:
        _deploy_binary_maven(suite, _map_to_maven_dist_name(mxMetaName), _mavenGroupId(suite.name), mxMetaJar, version, repo, settingsXml=args.settings, dryRun=args.dry_run)

    if not args.all_suites and suite == primary_suite() and suite.vc.kind == 'git' and suite.vc.active_branch(suite.vc_dir) == 'master':
        deploy_branch_name = 'binary'
        platform_dependent_base = deploy_branch_name + '_'
        binary_deployed_ref = platform_dependent_base + Distribution.platformName() if platform_dependence else deploy_branch_name
        deployed_rev = suite.version()
        assert deployed_rev == suite.vc.parent(suite.vc_dir), 'Version mismatch: suite.version() != suite.vc.parent(suite.vc_dir)'

        def try_remote_branch_update(branch_name):
            deploy_item_msg = "'{0}'-branch to {1}".format(branch_name, deployed_rev)
            log("On master branch: Try setting " + deploy_item_msg)
            retcode = GitConfig.set_branch(suite.vc_dir, branch_name, deployed_rev)
            if retcode:
                log("Updating " + deploy_item_msg + " failed (probably more recent deployment)")
            else:
                log("Sucessfully updated " + deploy_item_msg)

        try_remote_branch_update(binary_deployed_ref)

        if platform_dependence:
            log("Suite has platform_dependence: Update " + deploy_branch_name)
            platform_dependent_branches = GitConfig.get_matching_branches('origin', platform_dependent_base + '*', vcdir=suite.vc_dir)
            not_on_same_rev = [(branch_name, commit_id) for branch_name, commit_id in platform_dependent_branches.items() if commit_id != deployed_rev]
            if len(not_on_same_rev):
                log("Skip " + deploy_branch_name + " update! The following branches are not yet on " + deployed_rev + ":")
                for branch_name, commit_id in not_on_same_rev:
                    log("  " + branch_name + " --> " + commit_id)
            else:
                try_remote_branch_update(deploy_branch_name)


def _maven_deploy_dists(dists, versionGetter, repo, settingsXml,
                        dryRun=False,
                        validateMetadata='none',
                        gpg=False,
                        keyid=None,
                        generateJavadoc=False,
                        deployMapFiles=False,
                        deployRepoMetadata=False):
    if repo != maven_local_repository():
        # Non-local deployment requires license checking
        for dist in dists:
            if not dist.theLicense:
                abort('Distributions without license are not cleared for upload to {}: can not upload {}'.format(repo.name, dist.name))
            for distLicense in dist.theLicense:
                if distLicense not in repo.licenses:
                    abort('Distribution with {} license are not cleared for upload to {}: can not upload {}'.format(distLicense.name, repo.name, dist.name))
    if deployRepoMetadata:
        repo_metadata_xml = XMLDoc()
        repo_metadata_xml.open('suite-revisions')
        for s_ in suites():
            if s_.vc:
                commit_timestamp = s_.vc.parent_info(s_.vc_dir)['committer-ts']
                repo_metadata_xml.element('suite', attributes={
                    "name": s_.name,
                    "revision": s_.vc.parent(s_.vc_dir),
                    "date": datetime.utcfromtimestamp(commit_timestamp).isoformat(),
                    "kind": s_.vc.kind
                })
        repo_metadata_xml.close('suite-revisions')
        repo_metadata_fd, repo_metadata_name = mkstemp(suffix='.xml', text=True)
        repo_metadata = repo_metadata_xml.xml(indent='  ', newl='\n')
        if _opts.very_verbose or (dryRun and _opts.verbose):
            log(repo_metadata)
        with os.fdopen(repo_metadata_fd, 'w') as f:
            f.write(repo_metadata)
    else:
        repo_metadata_name = None
    for dist in dists:
        for platform in dist.platforms:
            if dist.maven_artifact_id() != dist.maven_artifact_id(platform):
                full_maven_name = "{}:{}".format(dist.maven_group_id(), dist.maven_artifact_id(platform))
                if repo == maven_local_repository():
                    log("Installing dummy {}".format(full_maven_name))
                    # Allow installing local dummy platform dependend artifacts for other platforms
                    foreign_platform_dummy_tarball = tempfile.NamedTemporaryFile('w', suffix='.tar.gz', delete=False)
                    foreign_platform_dummy_tarball.close()
                    with Archiver(foreign_platform_dummy_tarball.name, kind='tgz') as arc:
                        arc.add_str("Dummy artifact {} for local maven install\n".format(full_maven_name), full_maven_name + ".README", None)
                    _deploy_binary_maven(dist.suite, dist.maven_artifact_id(platform), dist.maven_group_id(), foreign_platform_dummy_tarball.name, versionGetter(dist.suite), repo, settingsXml=settingsXml, extension=dist.remoteExtension(), dryRun=dryRun)
                    os.unlink(foreign_platform_dummy_tarball.name)
                else:
                    logv("Skip deploying {}".format(full_maven_name))
            else:
                pomFile = _tmpPomFile(dist, versionGetter, validateMetadata)
                if _opts.very_verbose or (dryRun and _opts.verbose):
                    with open(pomFile) as f:
                        log(f.read())
                if dist.isJARDistribution():
                    javadocPath = None
                    if generateJavadoc:
                        projects = [p for p in dist.archived_deps() if p.isJavaProject()]
                        tmpDir = tempfile.mkdtemp(prefix='mx-javadoc')
                        javadocArgs = ['--base', tmpDir, '--unified', '--projects', ','.join((p.name for p in projects))]
                        if dist.javadocType == 'implementation':
                            javadocArgs += ['--implementation']
                        else:
                            assert dist.javadocType == 'api'
                        if dist.allowsJavadocWarnings:
                            javadocArgs += ['--allow-warnings']
                        javadoc(javadocArgs, includeDeps=False, mayBuild=False, quietForNoPackages=True)
                        tmpJavadocJar = tempfile.NamedTemporaryFile('w', suffix='.jar', delete=False)
                        tmpJavadocJar.close()
                        javadocPath = tmpJavadocJar.name
                        emptyJavadoc = True
                        with zipfile.ZipFile(javadocPath, 'w', compression=zipfile.ZIP_DEFLATED) as arc:
                            javadocDir = join(tmpDir, 'javadoc')
                            for (dirpath, _, filenames) in os.walk(javadocDir):
                                for filename in filenames:
                                    emptyJavadoc = False
                                    src = join(dirpath, filename)
                                    dst = os.path.relpath(src, javadocDir)
                                    arc.write(src, dst)
                        shutil.rmtree(tmpDir)
                        if emptyJavadoc:
                            javadocPath = None
                            warn('Javadoc for {0} was empty'.format(dist.name))

                    extraFiles = []
                    if deployMapFiles and dist.is_stripped():
                        extraFiles.append((dist.strip_mapping_file(), 'proguard', 'map'))
                    if repo_metadata_name:
                        extraFiles.append((repo_metadata_name, 'suite-revisions', 'xml'))

                    pushed_file = dist.prePush(dist.path)
                    pushed_src_file = dist.prePush(dist.sourcesPath)
                    _deploy_binary_maven(dist.suite, dist.maven_artifact_id(), dist.maven_group_id(), pushed_file, versionGetter(dist.suite), repo,
                                         srcPath=pushed_src_file,
                                         settingsXml=settingsXml,
                                         extension=dist.remoteExtension(),
                                         dryRun=dryRun,
                                         pomFile=pomFile,
                                         gpg=gpg, keyid=keyid,
                                         javadocPath=javadocPath,
                                         extraFiles=extraFiles)
                    if pushed_file != dist.path:
                        os.unlink(pushed_file)
                    if pushed_src_file != dist.sourcesPath:
                        os.unlink(pushed_src_file)
                    if javadocPath:
                        os.unlink(javadocPath)
                elif dist.isTARDistribution() or dist.isLayoutJARDistribution():
                    extraFiles = []
                    if repo_metadata_name:
                        extraFiles.append((repo_metadata_name, 'suite-revisions', 'xml'))
                    _deploy_binary_maven(dist.suite, dist.maven_artifact_id(), dist.maven_group_id(), dist.prePush(dist.path), versionGetter(dist.suite), repo,
                                         settingsXml=settingsXml,
                                         extension=dist.remoteExtension(),
                                         dryRun=dryRun,
                                         pomFile=pomFile,
                                         gpg=gpg, keyid=keyid,
                                         extraFiles=extraFiles)
                else:
                    warn('Unsupported distribution: ' + dist.name)
                os.unlink(pomFile)
    if repo_metadata_name:
        os.unlink(repo_metadata_name)


def maven_deploy(args):
    """deploy jars for the primary suite to remote maven repository

    All binaries must be built first using 'mx build'.
    """
    parser = ArgumentParser(prog='mx maven-deploy')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--only', action='store', help='Limit deployment to these distributions')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    parser.add_argument('--skip-existing', action='store_true', help='Do not deploy distributions if already in repository')
    parser.add_argument('--validate', help='Validate that maven metadata is complete enough for publication', default='compat', choices=['none', 'compat', 'full'])
    parser.add_argument('--suppress-javadoc', action='store_true', help='Suppress javadoc generation and deployment')
    parser.add_argument('--all-distribution-types', help='Include all distribution types. By default, only JAR distributions are included', action='store_true')
    parser.add_argument('--all-distributions', help='Include all distributions, regardless of the maven flags.', action='store_true')
    parser.add_argument('--version-string', action='store', help='Provide custom version string for deployment')
    parser.add_argument('--licenses', help='Comma-separated list of licenses that are cleared for upload. Only used if no url is given. Otherwise licenses are looked up in suite.py', default='')
    parser.add_argument('--gpg', action='store_true', help='Sign files with gpg before deploying')
    parser.add_argument('--gpg-keyid', help='GPG keyid to use when signing files (implies --gpg)', default=None)
    parser.add_argument('--with-suite-revisions-metadata', help='Deploy suite revisions metadata file', action='store_true')
    parser.add_argument('repository_id', metavar='repository-id', nargs='?', action='store', help='Repository ID used for Maven deploy')
    parser.add_argument('url', metavar='repository-url', nargs='?', action='store', help='Repository URL used for Maven deploy, if no url is given, the repository-id is looked up in suite.py')
    args = parser.parse_args(args)

    if args.gpg_keyid and not args.gpg:
        args.gpg = True
        logv('Implicitly setting gpg to true since a keyid was specified')

    _mvn.check()
    def versionGetter(suite):
        if args.version_string:
            return args.version_string
        return suite.release_version(snapshotSuffix='SNAPSHOT')

    if args.all_suites:
        _suites = suites()
    else:
        _suites = primary_or_specific_suites()

    def distMatcher(dist):
        if args.all_distributions:
            return True
        if not dist.isJARDistribution() and not args.all_distribution_types:
            return False
        return getattr(d, 'maven', False) and not dist.is_test_distribution() #pylint: disable=undefined-variable

    has_deployed_dist = False
    for s in _suites:
        dists = [d for d in s.dists if distMatcher(d)]
        if args.only:
            only = args.only.split(',')
            dists = [d for d in dists if d.name in only or d.qualifiedName() in only]

        if args.url:
            licenses = get_license(args.licenses.split(','))
            repo = Repository(None, args.repository_id, args.url, args.url, licenses)
        elif args.repository_id:
            if not s.getMxCompatibility().supportsRepositories():
                abort("Repositories are not supported in {}'s suite version".format(s.name))
            repo = repository(args.repository_id)
        else:
            repo = maven_local_repository()

        dists = _deploy_skip_existing(args, dists, versionGetter(s), repo)
        if not dists and not args.all_suites:
            warn("No distribution to deploy in " + s.name)
            continue

        for dist in dists:
            if not dist.exists():
                abort("'{0}' is not built, run 'mx build' first".format(dist.name))

        generateJavadoc = None if args.suppress_javadoc else s.getMxCompatibility().mavenDeployJavadoc()

        action = 'Installing' if repo == maven_local_repository() else 'Deploying'
        log('{} {} distributions for version {}'.format(action, s.name, versionGetter(s)))
        _maven_deploy_dists(dists, versionGetter, repo, args.settings,
                            dryRun=args.dry_run,
                            validateMetadata=args.validate,
                            gpg=args.gpg,
                            keyid=args.gpg_keyid,
                            generateJavadoc=generateJavadoc,
                            deployRepoMetadata=args.with_suite_revisions_metadata)
        has_deployed_dist = True
    if not has_deployed_dist:
        abort("No distribution was deployed!")

def maven_url(args):
    _artifact_url(args, 'mx maven-url', 'mx maven-deploy', lambda s: s.release_version('SNAPSHOT'))

def binary_url(args):
    _artifact_url(args, 'mx binary-url', 'mx deploy-binary', lambda s: '{0}-SNAPSHOT'.format(s.vc.parent(s.vc_dir)))

def _artifact_url(args, prog, deploy_prog, snapshot_version_fun):
    parser = ArgumentParser(prog=prog)
    parser.add_argument('repository_id', action='store', help='Repository name')
    parser.add_argument('dist_name', action='store', help='Distribution name')
    parser.add_argument('--no-sha1', action='store_false', dest='sha1', help='Do not display the URL of the .sha1 file')
    args = parser.parse_args(args)

    repo = repository(args.repository_id)
    dist = distribution(args.dist_name)

    group_id = dist.maven_group_id()
    artifact_id = dist.maven_artifact_id()
    snapshot_version = snapshot_version_fun(dist.suite)
    extension = dist.remoteExtension()

    maven_repo = MavenRepo(repo.get_url(snapshot_version))
    snapshot = maven_repo.getSnapshot(group_id, artifact_id, snapshot_version)

    if not snapshot:
        url = maven_repo.getSnapshotUrl(group_id, artifact_id, snapshot_version)
        abort('Version {} not found for {}:{} ({})\nNote that the binary must have been deployed with `{}`'.format(snapshot_version, group_id, artifact_id, url, deploy_prog))
    build = snapshot.getCurrentSnapshotBuild()
    try:
        url, sha1_url = build.getSubArtifact(extension)
        print(url)
        if args.sha1:
            print(sha1_url)
    except MavenSnapshotArtifact.NonUniqueSubArtifactException:
        abort('Multiple {}s found for {} in snapshot {} in repository {}'.format(extension, dist.remoteName(), build.version, maven_repo.repourl))

class MavenConfig:
    def __init__(self):
        self.has_maven = None
        self.missing = 'no mvn executable found'


    def check(self, abortOnError=True):
        if self.has_maven is None:
            try:
                run_maven(['--version'], out=lambda e: None)
                self.has_maven = True
            except OSError:
                self.has_maven = False
                warn(self.missing)

        if not self.has_maven:
            if abortOnError:
                abort(self.missing)
            else:
                warn(self.missing)

        return self if self.has_maven else None


### ~~~~~~~~~~~~~ VC, SCM
class SCMMetadata(object):
    def __init__(self, url, read, write):
        self.url = url
        self.read = read
        self.write = write


_dynamic_imports = None


def get_dynamic_imports():
    """
    :return: a list of tuples (suite_name, in_subdir)
    :rtype: (str, bool)
    """
    global _dynamic_imports
    if _dynamic_imports is None:
        dynamic_imports_from_env = get_env('DYNAMIC_IMPORTS')
        dynamic_imports = dynamic_imports_from_env.split(',') if dynamic_imports_from_env else []
        if _opts.dynamic_imports:
            for opt in _opts.dynamic_imports:
                dynamic_imports += opt.split(',')
        else:
            env_dynamic_imports = os.environ.get('DEFAULT_DYNAMIC_IMPORTS')
            if env_dynamic_imports:
                dynamic_imports += env_dynamic_imports.split(',')
        _dynamic_imports = []
        for dynamic_import in dynamic_imports:
            idx = dynamic_import.find('/')
            if idx < 0:
                _dynamic_imports.append((dynamic_import, False))
            else:
                _dynamic_imports.append((dynamic_import[idx + 1:], True))
    return _dynamic_imports


### ~~~~~~~~~~~~~ XML

class XMLElement(xml.dom.minidom.Element):
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "<" + self.tagName)

        attrs = self._get_attributes()
        a_names = sorted(attrs.keys())

        for a_name in a_names:
            writer.write(" %s=\"" % a_name)
            xml.dom.minidom._write_data(writer, attrs[a_name].value)
            writer.write("\"")
        if self.childNodes:
            if not self.ownerDocument.padTextNodeWithoutSiblings and len(self.childNodes) == 1 and isinstance(self.childNodes[0], xml.dom.minidom.Text):
                # if the only child of an Element node is a Text node, then the
                # text is printed without any indentation or new line padding
                writer.write(">")
                self.childNodes[0].writexml(writer)
                writer.write("</%s>%s" % (self.tagName, newl))
            else:
                writer.write(">%s" % (newl))
                for node in self.childNodes:
                    node.writexml(writer, indent + addindent, addindent, newl)
                writer.write("%s</%s>%s" % (indent, self.tagName, newl))
        else:
            writer.write("/>%s" % (newl))

class XMLDoc(xml.dom.minidom.Document):
    def __init__(self):
        xml.dom.minidom.Document.__init__(self)
        self.current = self
        self.padTextNodeWithoutSiblings = False

    def createElement(self, tagName):
        # overwritten to create XMLElement
        e = XMLElement(tagName)
        e.ownerDocument = self
        return e

    def comment(self, txt):
        self.current.appendChild(self.createComment(txt))

    def open(self, tag, attributes=None, data=None):
        if attributes is None:
            attributes = {}
        element = self.createElement(tag)
        for key, value in attributes.items():
            element.setAttribute(key, value)
        self.current.appendChild(element)
        self.current = element
        if data is not None:
            element.appendChild(self.createTextNode(data))
        return self

    def close(self, tag):
        assert self.current != self
        assert tag == self.current.tagName, str(tag) + ' != ' + self.current.tagName
        self.current = self.current.parentNode
        return self

    def element(self, tag, attributes=None, data=None):
        if attributes is None:
            attributes = {}
        return self.open(tag, attributes, data).close(tag)

    def xml(self, indent='', newl='', escape=False, standalone=None):
        assert self.current == self
        result = _decode(self.toprettyxml(indent, newl, encoding="UTF-8"))
        if not result.startswith('<?xml'):
            # include xml tag if it's not already included
            result = '<?xml version="1.0" encoding="UTF-8"?>\n' + result
        if escape:
            entities = {'"':  "&quot;", "'":  "&apos;", '\n': '&#10;'}
            result = xml.sax.saxutils.escape(result, entities)
        if standalone is not None:
            result = result.replace('encoding="UTF-8"?>', 'encoding="UTF-8" standalone="' + str(standalone) + '"?>')
        return result


mx_subst.results_substitutions.register_no_arg('os', get_os)


def get_opts():
    """
    Gets the parsed command line options.
    """
    assert _argParser.parsed is True
    return _opts


### ~~~~~~~~~~~~~ Project

def projects_from_names(projectNames):
    """
    Get the list of projects corresponding to projectNames; all projects if None
    """
    if projectNames is None:
        return projects()
    else:
        return [project(name) for name in projectNames]


def projects(opt_limit_to_suite=False, limit_to_primary=False):
    """
    Get the list of all loaded projects limited by --suite option if opt_limit_to_suite == True and by primary suite if limit_to_primary == True
    """

    sortedProjects = sorted((p for p in _projects.values() if not p.suite.internal))
    if opt_limit_to_suite:
        sortedProjects = _dependencies_opt_limit_to_suites(sortedProjects)
    if limit_to_primary:
        sortedProjects = _dependencies_limited_to_suites(sortedProjects, [primary_suite().name])
    return sortedProjects


def projects_opt_limit_to_suites():
    """
    Get the list of all loaded projects optionally limited by --suite option
    """
    return projects(opt_limit_to_suite=True)


def _dependencies_limited_to_suites(deps, suites):
    result = []
    for d in deps:
        s = d.suite
        if s.name in suites:
            result.append(d)
    return result


def _dependencies_opt_limit_to_suites(deps):
    if not _opts.specific_suites:
        return deps
    else:
        return _dependencies_limited_to_suites(deps, _opts.specific_suites)


def annotation_processors():
    """
    Get the list of all loaded projects that define an annotation processor.
    """
    global _annotationProcessors
    if _annotationProcessors is None:
        aps = set()
        for p in projects():
            for ap in p.annotation_processors():
                if project(ap, False):
                    aps.add(ap)
        _annotationProcessors = list(aps)
    return _annotationProcessors


def get_license(names, fatalIfMissing=True, context=None):

    def get_single_licence(name):
        if isinstance(name, License):
            return name
        _, name = splitqualname(name)
        l = _licenses.get(name)
        if l is None and fatalIfMissing:
            abort('license named ' + name + ' not found', context=context)
        return l

    if isinstance(names, str):
        names = [names]

    return [get_single_licence(name) for name in names]


def repository(name, fatalIfMissing=True, context=None):
    """ :rtype: Repository"""
    _, name = splitqualname(name)
    r = _repositories.get(name)
    if r is None and fatalIfMissing:
        abort('repository named ' + name + ' not found among ' + str(_repositories.keys()), context=context)
    return r


def splitqualname(name):
    pname = name.partition(":")
    if pname[0] != name:
        return pname[0], pname[2]
    else:
        return None, name


def _patchTemplateString(s, args, context):
    def _replaceVar(m):
        groupName = m.group(1)
        if not groupName in args:
            abort("Unknown parameter {}".format(groupName), context=context)
        return args[groupName]
    return re.sub(r'<(.+?)>', _replaceVar, s)

### Distribution

def instantiatedDistributionName(name, args, context):
    return _patchTemplateString(name, args, context).upper()


def reInstantiateDistribution(templateName, oldArgs, newArgs):
    _, name = splitqualname(templateName)
    context = "Template distribution " + name
    t = _distTemplates.get(name)
    if t is None:
        abort('Distribution template named ' + name + ' not found', context=context)
    oldName = instantiatedDistributionName(t.name, oldArgs, context)
    oldDist = t.suite._unload_unregister_distribution(oldName)
    newDist = instantiateDistribution(templateName, newArgs)
    newDist.update_listeners.update(oldDist.update_listeners)


def instantiateDistribution(templateName, args, fatalIfMissing=True, context=None):
    _, name = splitqualname(templateName)
    if not context:
        context = "Template distribution " + name
    t = _distTemplates.get(name)
    if t is None and fatalIfMissing:
        abort('Distribution template named ' + name + ' not found', context=context)
    missingParams = [p for p in t.parameters if p not in args]
    if missingParams:
        abort('Missing parameters while instantiating distribution template ' + t.name + ': ' + ', '.join(missingParams), context=t)

    def _patch(v):
        if isinstance(v, str):
            return _patchTemplateString(v, args, context)
        elif isinstance(v, dict):
            return {kk: _patch(vv) for kk, vv in v.items()}
        elif isinstance(v, list):
            return [_patch(e) for e in v]
        else:
            return v

    d = t.suite._load_distribution(instantiatedDistributionName(t.name, args, context), _patch(t.attrs))
    if d is None and fatalIfMissing:
        abort('distribution template ' + t.name + ' could not be instantiated with ' + str(args), context=t)
    t.suite._register_distribution(d)
    d.resolveDeps()
    d.post_init()
    return d


def _get_reasons_dep_was_removed(name, indent):
    """
    Gets the causality chain for the dependency named `name` being removed.
    Returns None if no dependency named `name` was removed.
    """
    reason = _removedDeps.get(name)
    if reason:
        if isinstance(reason, tuple):
            primary, secondary = reason
        else:
            primary = reason
            secondary = []
        causes = []

        r = _get_reasons_dep_was_removed(primary, indent + 1)
        if r:
            causes.append('{}{} was removed because {} was removed:'.format('  ' * indent, name, primary))
            causes.extend(r)
        else:
            causes.append(('  ' * indent) + primary + (':' if secondary else ''))

        for s in secondary:
            r = _get_reasons_dep_was_removed(s, indent + 1)
            if r:
                causes.extend(r)
            else:
                causes.append(('  ' * indent) + s)

        return causes
    return None


def _missing_dep_message(depName, depType):
    reasons = _get_reasons_dep_was_removed(depName, 1)
    if reasons:
        return '{} named {} was removed:\n{}'.format(depType, depName, '\n'.join(reasons))
    return '{} named {} was not found'.format(depType, depName)


def distribution(name, fatalIfMissing=True, context=None):
    """
    Get the distribution for a given name. This will abort if the named distribution does
    not exist and 'fatalIfMissing' is true.

    :rtype: Distribution
    """
    _, name = splitqualname(name)
    d = _dists.get(name)
    if d is None and fatalIfMissing:
        abort(_missing_dep_message(name, 'distribution'), context=context)
    return d


def dependency(name, fatalIfMissing=True, context=None):
    """
    Get the project, library or dependency for a given name. This will abort if the dependency
    not exist for 'name' and 'fatalIfMissing' is true.
    """
    if isinstance(name, Dependency):
        return name

    suite_name, name = splitqualname(name)
    if suite_name:
        # reference to a distribution or library from a suite
        referencedSuite = suite(suite_name, context=context)
        if referencedSuite:
            d = referencedSuite.dependency(name, fatalIfMissing=False, context=context)
            if d:
                return d
            else:
                if fatalIfMissing:
                    abort('cannot resolve ' + name + ' as a dependency defined by ' + suite_name, context=context)
                return None
    d = _projects.get(name)
    if d is None:
        d = _libs.get(name)
    if d is None:
        d = _jreLibs.get(name)
    if d is None:
        d = _jdkLibs.get(name)
    if d is None:
        d = _dists.get(name)
    if d is None and fatalIfMissing:
        if hasattr(_opts, 'ignored_projects') and name in _opts.ignored_projects:
            abort('dependency named ' + name + ' is ignored', context=context)
        abort(_missing_dep_message(name, 'dependency'), context=context)
    return d


def project(name, fatalIfMissing=True, context=None):
    """
    Get the project for a given name. This will abort if the named project does
    not exist and 'fatalIfMissing' is true.
    :rtype: Project
    """
    _, name = splitqualname(name)
    p = _projects.get(name)
    if p is None and fatalIfMissing:
        if name in _opts.ignored_projects:
            abort('project named ' + name + ' is ignored', context=context)
        abort(_missing_dep_message(name, 'project'), context=context)
    return p


def library(name, fatalIfMissing=True, context=None):
    """
    Gets the library for a given name. This will abort if the named library does
    not exist and 'fatalIfMissing' is true.

    As a convenience, if 'fatalIfMissing' is False, optional libraries that are not
    available are not returned ('None'  is returned instead).
    :rtype: BaseLibrary
    """
    l = _libs.get(name) or _jreLibs.get(name) or _jdkLibs.get(name)
    if l is None and fatalIfMissing:
        if _projects.get(name):
            abort(name + ' is a project, not a library', context=context)
        raise abort(_missing_dep_message(name, 'library'), context=context)
    if not fatalIfMissing and l.optional and not l.is_available():
        return None
    return l


def classpath_entries(names=None, includeSelf=True, preferProjects=False, excludes=None):
    """
    Gets the transitive set of dependencies that need to be on the class path
    given the root set of projects and distributions in `names`.

    :param names: a Dependency, str or list containing Dependency/str objects
    :type names: list or Dependency or str
    :param bool includeSelf: whether to include any of the dependencies in `names` in the returned list
    :param bool preferProjects: for a JARDistribution dependency, specifies whether to include
            it in the returned list (False) or to instead put its constituent dependencies on the
            the return list (True)
    :return: a list of Dependency objects representing the transitive set of dependencies that should
            be on the class path for something depending on `names`
    :rtype: list[ClasspathDependency]
    """
    if names is None:
        roots = set(dependencies())
    else:
        if isinstance(names, str):
            names = [names]
        elif isinstance(names, Dependency):
            names = [names]
        roots = [dependency(n) for n in names]
        invalid = [d for d in roots if not isinstance(d, ClasspathDependency)]
        if invalid:
            abort('class path roots must be classpath dependencies: ' + str(invalid))

    if not roots:
        return []

    if excludes is None:
        excludes = []
    else:
        if isinstance(excludes, str):
            excludes = [excludes]
        elif isinstance(excludes, Dependency):
            excludes = [excludes]
        excludes = [dependency(n) for n in excludes]

    assert len(set(roots) & set(excludes)) == 0

    cpEntries = []
    def _preVisit(dst, edge):
        if not isinstance(dst, ClasspathDependency):
            return False
        if dst in excludes:
            return False
        if dst in roots or dst.isLibrary() or dst.isJdkLibrary():
            return True
        if edge and edge.src.isJARDistribution() and edge.kind == DEP_STANDARD:
            preferDist = isinstance(edge.src.suite, BinarySuite) or not preferProjects
            return dst.isJARDistribution() if preferDist else dst.isProject()
        return True
    def _visit(dep, edge):
        if preferProjects and dep.isJARDistribution() and not isinstance(dep.suite, BinarySuite):
            return
        if not includeSelf and dep in roots:
            return
        cpEntries.append(dep)
    walk_deps(roots=roots, visit=_visit, preVisit=_preVisit, ignoredEdges=[DEP_ANNOTATION_PROCESSOR, DEP_BUILD])
    return cpEntries


def _entries_to_classpath(cpEntries, resolve=True, includeBootClasspath=False, jdk=None, unique=False, ignoreStripped=False, cp_prefix=None, cp_suffix=None):
    cp = []
    jdk = jdk or get_jdk()
    bcp_str = jdk.bootclasspath()
    bcp = bcp_str.split(os.pathsep) if bcp_str else []

    def _filecmp(a, b):
        if not exists(a) or not exists(b):
            return a == b
        return filecmp.cmp(a, b)

    def _appendUnique(cp_addition):
        for new_path in cp_addition.split(os.pathsep):
            if (not unique or not any((_filecmp(d, new_path) for d in cp))) \
                    and (includeBootClasspath or not any((_filecmp(d, new_path) for d in bcp))):
                cp.append(new_path)
    if includeBootClasspath:
        if bcp_str:
            _appendUnique(bcp_str)
    if _opts.cp_prefix is not None:
        _appendUnique(_opts.cp_prefix)
    if cp_prefix is not None:
        _appendUnique(cp_prefix)
    for dep in cpEntries:
        if dep.isJdkLibrary() or dep.isJreLibrary():
            cp_repr = dep.classpath_repr(jdk, resolve=resolve)
        elif dep.isJARDistribution() and ignoreStripped:
            cp_repr = dep.original_path()
        else:
            cp_repr = dep.classpath_repr(resolve)
        if cp_repr:
            _appendUnique(cp_repr)
    if cp_suffix is not None:
        _appendUnique(cp_suffix)
    if _opts.cp_suffix is not None:
        _appendUnique(_opts.cp_suffix)

    return os.pathsep.join(cp)


def classpath(names=None, resolve=True, includeSelf=True, includeBootClasspath=False, preferProjects=False, jdk=None, unique=False, ignoreStripped=False):
    """
    Get the class path for a list of named projects and distributions, resolving each entry in the
    path (e.g. downloading a missing library) if 'resolve' is true. If 'names' is None,
    then all registered dependencies are used.
    """
    cpEntries = classpath_entries(names=names, includeSelf=includeSelf, preferProjects=preferProjects)
    return _entries_to_classpath(cpEntries=cpEntries, resolve=resolve, includeBootClasspath=includeBootClasspath, jdk=jdk, unique=unique, ignoreStripped=ignoreStripped)


def get_runtime_jvm_args(names=None, cp_prefix=None, cp_suffix=None, jdk=None):
    """
    Get the VM arguments (e.g. classpath and system properties) for a list of named projects and
    distributions. If 'names' is None, then all registered dependencies are used.
    """
    cpEntries = classpath_entries(names=names)
    ret = ["-cp", _separatedCygpathU2W(_entries_to_classpath(cpEntries, cp_prefix=cp_prefix, cp_suffix=cp_suffix, jdk=jdk))]

    def add_props(d):
        if hasattr(d, "getJavaProperties"):
            for key, value in d.getJavaProperties().items():
                ret.append("-D" + key + "=" + value)

    for dep in cpEntries:
        add_props(dep)

        # also look through the individual projects inside all distributions on the classpath
        if dep.isDistribution():
            for project in dep.archived_deps():
                add_props(project)

    return ret


def classpath_walk(names=None, resolve=True, includeSelf=True, includeBootClasspath=False, jdk=None):
    """
    Walks the resources available in a given classpath, yielding a tuple for each resource
    where the first member of the tuple is a directory path or ZipFile object for a
    classpath entry and the second member is the qualified path of the resource relative
    to the classpath entry.
    """
    cp = classpath(names, resolve, includeSelf, includeBootClasspath, jdk=jdk)
    for entry in cp.split(os.pathsep):
        if not exists(entry):
            continue
        if isdir(entry):
            for root, dirs, files in os.walk(entry):
                for d in dirs:
                    entryPath = join(root[len(entry) + 1:], d)
                    yield entry, _encode(entryPath)
                for f in files:
                    entryPath = join(root[len(entry) + 1:], f)
                    yield entry, _encode(entryPath)
        elif entry.endswith('.jar') or entry.endswith('.zip'):
            with zipfile.ZipFile(entry, 'r') as zf:
                for zi in zf.infolist():
                    entryPath = zi.filename
                    yield zf, _encode(entryPath)


def read_annotation_processors(path):
    r"""
    Reads the META-INF/services/javax.annotation.processing.Processor file based
    in the directory or zip file located at 'path'. Returns the list of lines
    in the file or None if the file does not exist at 'path'.

    From http://docs.oracle.com/javase/8/docs/api/java/util/ServiceLoader.html:

    A service provider is identified by placing a provider-configuration file in
    the resource directory META-INF/services. The file's name is the fully-qualified
    binary name of the service's type. The file contains a list of fully-qualified
    binary names of concrete provider classes, one per line. Space and tab
    characters surrounding each name, as well as blank lines, are ignored.
    The comment character is '#' ('\u0023', NUMBER SIGN); on each line all characters
    following the first comment character are ignored. The file must be encoded in UTF-8.
    """

    def parse(fp):
        lines = []
        for line in fp:
            line = line.split('#')[0].strip()
            if line:
                lines.append(line)
        return lines

    if exists(path):
        name = 'META-INF/services/javax.annotation.processing.Processor'
        if isdir(path):
            configFile = join(path, name.replace('/', os.sep))
            if exists(configFile):
                with open(configFile) as fp:
                    return parse(fp)
        else:
            assert path.endswith('.jar') or path.endswith('.zip'), path
            with zipfile.ZipFile(path, 'r') as zf:
                if name in zf.namelist():
                    with zf.open(name) as fp:
                        return parse(fp)
    return None


def dependencies(opt_limit_to_suite=False):
    """
    Gets an iterable over all the registered dependencies. If changes are made to the registered
    dependencies during iteration, the behavior of the iterator is undefined. If 'types' is not
    None, only dependencies of a type in 'types
    """
    it = itertools.chain(_projects.values(), _libs.values(), _dists.values(), _jdkLibs.values(), _jreLibs.values())
    if opt_limit_to_suite and _opts.specific_suites:
        it = filter(lambda d: d.suite.name in _opts.specific_suites, it)
    return it


def defaultDependencies(opt_limit_to_suite=False):
    """
    Returns a tuple of removed non-default dependencies (i.e., attribute `defaultBuild=False`) and default dependencies.
    """
    deps = []
    removedDeps = []
    for d in dependencies(opt_limit_to_suite):
        if hasattr(d, "defaultBuild"):
            if d.defaultBuild is False:
                removedDeps.append(d)
            elif d.defaultBuild is True:
                deps.append(d)
            else:
                abort('Unsupported value "{}" {} for entry {}. The only supported values are boolean True or False.'.format(d.defaultBuild, type(d.defaultBuild), d.name))
        else:
            deps.append(d)
    return removedDeps, deps


def walk_deps(roots=None, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
    """
    Walks a spanning tree of the dependency graph. The first time a dependency `dep` is seen, if the
    `preVisit` function is None or returns a true condition, then the unvisited dependencies of `dep` are
    walked. Once all the dependencies of `dep` have been visited and `visit` is not None,
    it is applied with the same arguments as for `preVisit` and the return value is ignored.
    Note that `visit` is not called if `preVisit` returns a false condition.

    :param roots: from which to start traversing. If None, then `dependencies()` is used
    :param preVisit: None or a function called the first time a `Dependency` in the graph is seen.
           The arguments passed to this function are the `Dependency` being pre-visited and
           a `DepEdge` object representing the last edge in the path of dependencies walked
           to arrive the `Dependency`.
    :param visit: None or a function with same signature as `preVisit`.
    :param ignoredEdges: an iterable of values from `DEP_KINDS` specifying edge types to be ignored in the traversal.
           If None, then `[DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED, DEP_BUILD]` will be used.
    :param visitEdge: None or a function called for every out edge of a node in the traversed graph.
           The arguments passed to this function are the source `Dependency` of the edge, the destination
           `Dependency` and a `DepEdge` value for the edge that can also be used to trace the path from
           a traversal root to the edge.
    """
    visited = set()
    for dep in dependencies() if not roots else roots:
        dep.walk_deps(preVisit, visit, visited, ignoredEdges, visitEdge)


def sorted_dists():
    """
    Gets distributions sorted such that each distribution comes after
    any distributions it depends upon.
    """
    dists = []
    def add_dist(dist):
        if not dist in dists:
            for dep in dist.deps:
                if dep.isDistribution():
                    add_dist(dep)
            if not dist in dists:
                dists.append(dist)

    for d in _dists.values():
        add_dist(d)
    return dists

#: The HotSpot options that have an argument following them on the command line
_VM_OPTS_SPACE_SEPARATED_ARG = ['-mp', '-modulepath', '-limitmods', '-addmods', '-upgrademodulepath', '-m',
                        '--module-path', '--limit-modules', '--add-modules', '--upgrade-module-path',
                        '--module', '--module-source-path', '--add-exports', '--add-reads',
                        '--patch-module', '--boot-class-path', '--source-path']

def extract_VM_args(args, useDoubleDash=False, allowClasspath=False, defaultAllVMArgs=True):
    """
    Partitions `args` into a leading sequence of HotSpot VM options and the rest. If
    `useDoubleDash` then `args` is partititioned by the first instance of "--". If
    not `allowClasspath` then mx aborts if "-cp" or "-classpath" is in `args`.

   """
    for i in range(len(args)):
        if useDoubleDash:
            if args[i] == '--':
                vmArgs = args[:i]
                remainder = args[i + 1:]
                return vmArgs, remainder
        else:
            if not args[i].startswith('-'):
                if i != 0 and (args[i - 1] == '-cp' or args[i - 1] == '-classpath'):
                    if not allowClasspath:
                        abort('Cannot supply explicit class path option')
                    else:
                        continue
                if i != 0 and (args[i - 1] in _VM_OPTS_SPACE_SEPARATED_ARG):
                    continue
                vmArgs = args[:i]
                remainder = args[i:]
                return vmArgs, remainder

    if defaultAllVMArgs:
        return args, []
    else:
        return [], args


def _format_commands():
    msg = '\navailable commands:\n'
    commands = _mx_commands.commands()
    sorted_commands = sorted([k for k in commands.keys() if ':' not in k]) + sorted([k for k in commands.keys() if ':' in k])
    msg += _mx_commands.list_commands(sorted_commands)
    return msg + '\n'


### ~~~~~~~~~~~~~ JDK

"""
A factory for creating JDKConfig objects.
"""
class JDKFactory:
    def getJDKConfig(self):
        nyi('getJDKConfig', self)

    def description(self):
        nyi('description', self)

### ~~~~~~~~~~~~~ Debugging

def is_debug_lib_file(fn):
    return fn.endswith(add_debug_lib_suffix(""))

class DisableJavaDebugging(object):
    """ Utility for temporarily disabling java remote debugging.

    Should be used in conjunction with the ``with`` keywords, e.g.
    ```
    with DisableJavaDebugging():
        # call to JDKConfig.run_java
    ```
    """
    _disabled = False

    def __enter__(self):
        self.old = DisableJavaDebugging._disabled
        DisableJavaDebugging._disabled = True

    def __exit__(self, t, value, traceback):
        DisableJavaDebugging._disabled = self.old


class DisableJavaDebuggging(DisableJavaDebugging):
    def __init__(self, *args, **kwargs):
        super(DisableJavaDebuggging, self).__init__(*args, **kwargs)
        if primary_suite().getMxCompatibility().excludeDisableJavaDebuggging():
            abort('Class DisableJavaDebuggging is deleted in version 5.68.0 as it is misspelled.')


def is_debug_disabled():
    return DisableJavaDebugging._disabled

### JDK

def addJDKFactory(tag, compliance, factory):
    assert tag != DEFAULT_JDK_TAG
    complianceMap = _jdkFactories.setdefault(tag, {})
    complianceMap[compliance] = factory


def _getJDKFactory(tag, versionCheck):
    if tag not in _jdkFactories:
        return None
    complianceMap = _jdkFactories[tag]
    for compliance in sorted(complianceMap.keys(), reverse=True):
        if not versionCheck or versionCheck(VersionSpec(str(compliance))):
            return complianceMap[compliance]
    return None


"""
A namedtuple for the result of get_jdk_option().
"""
TagCompliance = namedtuple('TagCompliance', ['tag', 'compliance'])

_jdk_option = None


def get_jdk_option():
    """
    Gets the tag and compliance (as a TagCompliance object) derived from the --jdk option.
    If the --jdk option was not specified, both fields of the returned tuple are None.
    """
    global _jdk_option
    if _jdk_option is None:
        option = _opts.jdk
        if not option:
            option = os.environ.get('DEFAULT_JDK')
        if not option:
            jdktag = None
            jdkCompliance = None
        else:
            tag_compliance = option.split(':')
            if len(tag_compliance) == 1:
                if len(tag_compliance[0]) > 0:
                    if tag_compliance[0][0].isdigit():
                        jdktag = None
                        jdkCompliance = JavaCompliance(tag_compliance[0])
                    else:
                        jdktag = tag_compliance[0]
                        jdkCompliance = None
                else:
                    jdktag = None
                    jdkCompliance = None
            else:
                if len(tag_compliance) != 2 or not tag_compliance[0] or not tag_compliance[1]:
                    abort('Could not parse --jdk argument \'{}\' (should be of the form "[tag:]compliance")'.format(option))
                jdktag = tag_compliance[0]
                try:
                    jdkCompliance = JavaCompliance(tag_compliance[1])
                except AssertionError as e:
                    raise abort('Could not parse --jdk argument \'{}\' (should be of the form "[tag:]compliance")\n{}'.format(option, e))

        if jdktag and jdktag != DEFAULT_JDK_TAG:
            factory = _getJDKFactory(jdktag, jdkCompliance._exact_match if jdkCompliance else None)
            if not factory:
                if len(_jdkFactories) == 0:
                    abort("No JDK providers available")
                available = []
                for t, m in _jdkFactories.items():
                    for c in m:
                        available.append('{}:{}'.format(t, c))
                abort("No provider for '{}:{}' JDK (available: {})".format(jdktag, jdkCompliance if jdkCompliance else '*', ', '.join(available)))

        _jdk_option = TagCompliance(jdktag, jdkCompliance)
    return _jdk_option


DEFAULT_JDK_TAG = 'default'


def _is_supported_by_jdt(jdk):
    """
    Determines if a specified JDK is supported by the Eclipse JDT compiler.

    :param jdk: a :class:`mx.JDKConfig` object or a tag that can be used to get a JDKConfig object from :method:`get_jdk`
    :type jdk: :class:`mx.JDKConfig` or string
    :rtype: bool
    """
    if isinstance(jdk, str):
        jdk = get_jdk(tag=jdk)
    else:
        assert isinstance(jdk, JDKConfig)
    return jdk.javaCompliance < '9'


_jdks_cache = {}
_canceled_jdk_requests = set()


def get_jdk(versionCheck=None, purpose=None, cancel=None, versionDescription=None, tag=None, **kwargs):
    """
    Get a JDKConfig object matching the provided criteria.

    The JDK is selected by consulting the --jdk option, the --java-home option,
    the JAVA_HOME environment variable, the --extra-java-homes option and the
    EXTRA_JAVA_HOMES enviroment variable in that order.
    """
    cache_key = (versionCheck, tag)
    if cache_key in _jdks_cache:
        return _jdks_cache.get(cache_key)

    # Precedence for JDK to use:
    # 1. --jdk option value
    # 2. JDK specified by set_java_command_default_jdk_tag
    # 3. JDK selected by DEFAULT_JDK_TAG tag

    default_query = versionCheck is None and tag is None

    if tag is None:
        jdkOpt = get_jdk_option()
        if versionCheck is None and jdkOpt.compliance:
            versionCheck, versionDescription = jdkOpt.compliance.as_version_check()
        tag = jdkOpt.tag if jdkOpt.tag else DEFAULT_JDK_TAG

    defaultJdk = default_query and not purpose

    # Backwards compatibility support
    if kwargs:
        assert len(kwargs) == 1 and 'defaultJdk' in kwargs, 'unsupported arguments: ' + str(kwargs)
        defaultJdk = kwargs['defaultJdk']

    # interpret string and compliance as compliance check
    if isinstance(versionCheck, str):
        versionCheck = JavaCompliance(versionCheck)
    if isinstance(versionCheck, JavaCompliance):
        versionCheck, versionDescription = versionCheck.as_version_check()

    if tag != DEFAULT_JDK_TAG:
        factory = _getJDKFactory(tag, versionCheck)
        if factory:
            jdk = factory.getJDKConfig()
            if jdk.tag is not None:
                assert jdk.tag == tag
            else:
                jdk.tag = tag
        else:
            jdk = None
        if jdk is not None or default_query:
            _jdks_cache[cache_key] = jdk
            return jdk

    global _default_java_home, _extra_java_homes
    if cancel and (versionDescription, purpose) in _canceled_jdk_requests:
        return None

    def abort_not_found():
        msg = 'Could not find a JDK'
        if versionDescription:
            msg += ' ' + versionDescription
        if purpose:
            msg += ' for ' + purpose
        import select_jdk
        available = _filtered_jdk_configs(select_jdk.find_system_jdks(), versionCheck)
        if available:
            msg += '\nThe following JDKs are available:\n  ' + '\n  '.join(sorted([jdk.home for jdk in available]))

        msg += '\nSpecify one with the --java-home or --extra-java-homes option or with the JAVA_HOME or EXTRA_JAVA_HOMES environment variable.'
        p = _findPrimarySuiteMxDir()
        if p:
            msg += '\nOr run `{}/select_jdk.py -p {}` to set and persist these variables in {}.'.format(dirname(__file__), dirname(p), join(p, 'env'))
        else:
            msg += '\nOr run `{}/select_jdk.py` to set these variables.'.format(dirname(__file__))
        abort(msg)

    if defaultJdk:
        if not _default_java_home:
            _default_java_home = _find_jdk(versionCheck=versionCheck, versionDescription=versionDescription)
            if not _default_java_home:
                if not cancel:
                    abort_not_found()
                assert versionDescription or purpose
                _canceled_jdk_requests.add((versionDescription, purpose))
        _jdks_cache[cache_key] = _default_java_home
        return _default_java_home

    existing_java_homes = _extra_java_homes
    if _default_java_home:
        existing_java_homes.append(_default_java_home)
    for jdk in existing_java_homes:
        if not versionCheck or versionCheck(jdk.version):
            _jdks_cache[cache_key] = jdk
            return jdk

    jdk = _find_jdk(versionCheck=versionCheck, versionDescription=versionDescription)
    if jdk:
        assert jdk not in _extra_java_homes
        _extra_java_homes = _sorted_unique_jdk_configs(_extra_java_homes + [jdk])
    elif not cancel:
        abort_not_found()
    else:
        assert versionDescription or purpose
        _canceled_jdk_requests.add((versionDescription, purpose))
    _jdks_cache[cache_key] = jdk
    return jdk

def _find_jdk(versionCheck=None, versionDescription=None):
    """
    Selects a JDK and returns a JDKConfig object representing it.

    The selection is attempted from the --java-home option, the JAVA_HOME
    environment variable, the --extra-java-homes option and the EXTRA_JAVA_HOMES
    enviroment variable in that order.

    :param versionCheck: a predicate to be applied when making the selection
    :param versionDescription: a description of `versionPredicate` (e.g. ">= 1.8 and < 1.8.0u20 or >= 1.8.0u40")
    :return: the JDK selected or None
    """
    assert (versionDescription and versionCheck) or (not versionDescription and not versionCheck)
    if not versionCheck:
        versionCheck = lambda _: True

    candidateJdks = []
    source = ''
    if _opts and _opts.java_home:
        candidateJdks.append(_opts.java_home)
        source = '--java-home'
    elif os.environ.get('JAVA_HOME'):
        candidateJdks.append(os.environ.get('JAVA_HOME'))
        source = 'JAVA_HOME'

    if candidateJdks:
        result = _filtered_jdk_configs(candidateJdks, versionCheck, missingIsError=True, source=source)
        if result:
            if source == '--java-home' and os.environ.get('JAVA_HOME'):
                os.environ['JAVA_HOME'] = _opts.java_home
            return result[0]

    candidateJdks = []
    if _opts.extra_java_homes:
        candidateJdks += _opts.extra_java_homes.split(os.pathsep)
        source = '--extra-java-homes'
    elif os.environ.get('EXTRA_JAVA_HOMES'):
        candidateJdks += os.environ.get('EXTRA_JAVA_HOMES').split(os.pathsep)
        source = 'EXTRA_JAVA_HOMES'

    result = _filtered_jdk_configs(candidateJdks, versionCheck, missingIsError=False, source=source)
    if result:
        return result[0]
    return None

def _sorted_unique_jdk_configs(configs):
    path_seen = set()
    unique_configs = [c for c in configs if c.home not in path_seen and not path_seen.add(c.home)]

    def _compare_configs(c1, c2):
        if c1 == _default_java_home:
            if c2 != _default_java_home:
                return 1
        elif c2 == _default_java_home:
            return -1
        if c1 in _extra_java_homes:
            if c2 not in _extra_java_homes:
                return 1
        elif c2 in _extra_java_homes:
            return -1
        return VersionSpec.__cmp__(c1.version, c2.version)
    return sorted(unique_configs, key=cmp_to_key(_compare_configs), reverse=True)

def is_interactive():
    if get_env('CONTINUOUS_INTEGRATION'):
        return False
    return not sys.stdin.closed and sys.stdin.isatty()

_probed_JDKs = {}

def _probe_JDK(home):
    res = _probed_JDKs.get(home)
    if not res:
        try:
            res = JDKConfig(home)
        except JDKConfigException as e:
            res = e
        _probed_JDKs[home] = res
    return res

def _filtered_jdk_configs(candidates, versionCheck, missingIsError=False, source=None):
    filtered = []
    for candidate in candidates:
        jdk = _probe_JDK(candidate)
        if isinstance(jdk, JDKConfigException):
            if source:
                message = 'Path in ' + source + ' is not pointing to a JDK (' + jdk.message + '): ' + candidate
                if is_darwin():
                    candidate = join(candidate, 'Contents', 'Home')
                    if not isinstance(_probe_JDK(candidate), JDKConfigException):
                        message += '. Set ' + source + ' to ' + candidate + ' instead.'

                if missingIsError:
                    abort(message)
                else:
                    warn(message)
        else:
            if not versionCheck or versionCheck(jdk.version):
                filtered.append(jdk)
    return filtered

def find_classpath_arg(vmArgs):
    """
    Searches for the last class path argument in `vmArgs` and returns its
    index and value as a tuple. If no class path argument is found, then
    the tuple (None, None) is returned.
    """
    # If the last argument is '-cp' or '-classpath' then it is not
    # valid since the value is missing. As such, we ignore the
    # last argument.
    for index in reversed(range(len(vmArgs) - 1)):
        if vmArgs[index] in ['-cp', '-classpath']:
            return index + 1, vmArgs[index + 1]
    return None, None

_java_command_default_jdk_tag = None

def set_java_command_default_jdk_tag(tag):
    global _java_command_default_jdk_tag
    assert _java_command_default_jdk_tag is None, 'TODO: need policy for multiple attempts to set the default JDK for the "java" command'
    _java_command_default_jdk_tag = tag


### Java command

def java_command(args):
    """run the java executable in the selected JDK

    The JDK is selected by consulting the --jdk option, the --java-home option,
    the JAVA_HOME environment variable, the --extra-java-homes option and the
    EXTRA_JAVA_HOMES enviroment variable in that order.
    """
    run_java(args)

def run_java(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, addDefaultArgs=True, jdk=None):
    """
    Runs a Java program by executing the java executable in a JDK.
    """
    if jdk is None:
        jdk = get_jdk()
    return jdk.run_java(args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, cwd=cwd, timeout=timeout, env=env, addDefaultArgs=addDefaultArgs)

def run_java_min_heap(args, benchName='# MinHeap:', overheadFactor=1.5, minHeap=0, maxHeap=2048, repetitions=1, out=None, err=None, cwd=None, timeout=None, env=None, addDefaultArgs=True, jdk=None):
    """computes the minimum heap size required to run a Java program within a certain overhead factor"""
    assert minHeap <= maxHeap

    def run_with_heap(heap, args, timeout=timeout, suppressStderr=True, nonZeroIsFatal=False):
        log('Trying with %sMB of heap...' % heap)
        with open(os.devnull, 'w') as fnull:
            vmArgs, pArgs = extract_VM_args(args=args, useDoubleDash=False, allowClasspath=True, defaultAllVMArgs=True)
            exitCode = run_java(vmArgs + ['-Xmx%dM' % heap] + pArgs, nonZeroIsFatal=nonZeroIsFatal, out=out, err=fnull if suppressStderr else err, cwd=cwd, timeout=timeout, env=env, addDefaultArgs=addDefaultArgs)
            if exitCode:
                log('failed')
            else:
                log('succeeded')
            return exitCode

    if overheadFactor > 0:
        t = time.time()
        if run_with_heap(maxHeap, args, timeout=timeout, suppressStderr=False):
            log('The reference heap (%sMB) is too low.' % maxHeap)
            return 1
        referenceTime = time.time() - t
        maxTime = referenceTime * overheadFactor
        log('Reference time = ' + str(referenceTime))
        log('Maximum time = ' + str(maxTime))
    else:
        maxTime = None

    currMin = minHeap
    currMax = maxHeap
    lastSuccess = maxHeap

    while currMax >= currMin:
        logv('Min = %s; Max = %s' % (currMin, currMax))
        avg = (currMax + currMin) / 2

        successful = 0
        while successful < repetitions:
            if run_with_heap(avg, args, timeout=maxTime):
                break
            else:
                successful += 1

        if successful == repetitions:
            lastSuccess = avg
            currMax = avg - 1
        else:
            currMin = avg + 1

    # We cannot bisect further. The last succesful attempt is the result.
    log('%s %s' % (benchName, lastSuccess))

def _kill_process(pid, sig):
    """
    Sends the signal `sig` to the process identified by `pid`. If `pid` is a process group
    leader, then signal is sent to the process group id.
    """
    pgid = os.getpgid(pid)
    try:
        logvv('[{} sending {} to {}]'.format(os.getpid(), sig, pid))
        if pgid == pid:
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
        return True
    except:
        log('Error killing subprocess ' + str(pid) + ': ' + str(sys.exc_info()[1]))
        return False

def _waitWithTimeout(process, args, timeout, nonZeroIsFatal=True):
    def _waitpid(pid):
        while True:
            try:
                return os.waitpid(pid, os.WNOHANG)
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                raise

    def _returncode(status):
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        elif os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        else:
            # Should never happen
            raise RuntimeError("Unknown child exit status!")

    end = time.time() + timeout
    delay = 0.0005
    while True:
        (pid, status) = _waitpid(process.pid)
        if pid == process.pid:
            return _returncode(status)
        remaining = end - time.time()
        if remaining <= 0:
            msg = 'Process timed out after {0} seconds: {1}'.format(timeout, ' '.join(args))
            if nonZeroIsFatal:
                abort(msg)
            else:
                log(msg)
                _kill_process(process.pid, signal.SIGKILL)
                return ERROR_TIMEOUT
        delay = min(delay * 2, remaining, .05)
        time.sleep(delay)

# Makes the current subprocess accessible to the abort() function
# This is a list of tuples of the subprocess.Popen or
# multiprocessing.Process object and args.
_currentSubprocesses = []

def _addSubprocess(p, args):
    entry = (p, args)
    logvv('[{}: started subprocess {}: {}]'.format(os.getpid(), p.pid, args))
    _currentSubprocesses.append(entry)
    return entry

def _removeSubprocess(entry):
    if entry and entry in _currentSubprocesses:
        try:
            _currentSubprocesses.remove(entry)
        except:
            pass

def waitOn(p):
    if is_windows():
        # on windows use a poll loop, otherwise signal does not get handled
        retcode = None
        while retcode is None:
            retcode = p.poll()
            time.sleep(0.05)
    else:
        retcode = p.wait()
    return retcode

def _parse_http_proxy(envVarNames):
    """
    Parses the value of the first existing environment variable named
    in `envVarNames` into a host and port tuple where port is None if
    it's not present in the environment variable.
    """
    p = re.compile(r'(?:https?://)?([^:]+):?(\d+)?/?$')
    for name in envVarNames:
        value = get_env(name)
        if value:
            m = p.match(value)
            if m:
                return m.group(1), m.group(2)
            else:
                abort("Value of " + name + " is not valid:  " + value)
    return (None, None)

def _java_no_proxy(env_vars=None):
    if env_vars is None:
        env_vars = ['no_proxy', 'NO_PROXY']
    java_items = []
    for name in env_vars:
        value = get_env(name)
        if value:
            items = value.split(',')
            for item in items:
                item = item.strip()
                if item == '*':
                    java_items += [item]
                elif item.startswith("."):
                    java_items += ["*" + item]
                else:
                    java_items += [item]
    return '|'.join(java_items)

def run_maven(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None):
    proxyArgs = []
    def add_proxy_property(name, value):
        if value:
            return proxyArgs.append('-D' + name + '=' + value)

    host, port = _parse_http_proxy(["HTTP_PROXY", "http_proxy"])
    add_proxy_property('proxyHost', host)
    add_proxy_property('proxyPort', port)
    host, port = _parse_http_proxy(["HTTPS_PROXY", "https_proxy"])
    add_proxy_property('https.proxyHost', host)
    add_proxy_property('https.proxyPort', port)
    java_no_proxy = _java_no_proxy()
    if is_windows():
        # `no_proxy` is already set in the Maven settings file.
        # To pass it here we need a reliable way to escape, e.g., the `|` separator
        pass
    else:
        add_proxy_property('http.nonProxyHosts', java_no_proxy)

    extra_args = []
    if proxyArgs:
        proxyArgs.append('-DproxySet=true')
        extra_args.extend(proxyArgs)

    if _opts.very_verbose:
        extra_args += ['--debug']


    mavenCommand = 'mvn'
    if is_windows():
        mavenCommand += '.cmd'
        extra_args += ['--batch-mode'] # prevent maven to color output
    mavenHome = get_env('MAVEN_HOME')
    if mavenHome:
        mavenCommand = join(mavenHome, 'bin', mavenCommand)
    return run([mavenCommand] + extra_args + args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, timeout=timeout, env=env, cwd=cwd)

def run_mx(args, suite=None, mxpy=None, nonZeroIsFatal=True, out=None, err=None, timeout=None, env=None, quiet=False):
    """
    Recursively runs mx.

    :param list args: the command line arguments to pass to the recusive mx execution
    :param suite: the primary suite or primary suite directory to use
    :param str mxpy: path the mx module to run (None to use the current mx module)
    """
    if mxpy is None:
        mxpy = join(_mx_home, 'mx.py')
    commands = [sys.executable, '-u', mxpy, '--java-home=' + get_jdk().home]
    cwd = None
    if suite:
        if isinstance(suite, str):
            commands += ['-p', suite]
            cwd = suite
        else:
            commands += ['-p', suite.dir]
            cwd = suite.dir
    if quiet:
        commands.append('--no-warning')
    elif get_opts().verbose:
        if get_opts().very_verbose:
            commands.append('-V')
        else:
            commands.append('-v')
    if _opts.version_conflict_resolution != 'suite':
        commands += ['--version-conflict-resolution', _opts.version_conflict_resolution]
    return run(commands + args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, timeout=timeout, env=env, cwd=cwd)

def _get_new_progress_group_args():
    """
    Gets a tuple containing the `preexec_fn` and `creationflags` parameters to subprocess.Popen
    required to create a subprocess that can be killed via os.killpg without killing the
    process group of the parent process.
    """
    preexec_fn = None
    creationflags = 0
    if is_windows():
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        preexec_fn = os.setsid
    return preexec_fn, creationflags

def run(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, stdin=None, **kwargs):
    """
    Run a command in a subprocess, wait for it to complete and return the exit status of the process.
    If the command times out, it kills the subprocess and returns `ERROR_TIMEOUT` if `nonZeroIsFatal`
    is false, otherwise it kills all subprocesses and raises a SystemExit exception.
    If the exit status of the command is non-zero, mx is exited with the same exit status if
    `nonZeroIsFatal` is true, otherwise the exit status is returned.
    Each line of the standard output and error streams of the subprocess are redirected to
    out and err if they are callable objects.
    """
    assert stdin is None or isinstance(stdin, str), "'stdin' must be a string: " + str(stdin)
    assert isinstance(args, list), "'args' must be a list: " + str(args)
    idx = 0
    for arg in args:
        if not isinstance(arg, str):
            abort('Type of argument {} is not str but {}: {}\nArguments: {}'.format(idx, type(arg).__name__, arg, args))
        idx = idx + 1

    if env is None:
        env = os.environ.copy()

    vm_prefix = []
    if hasattr(_opts, 'vm_prefix') and _opts.vm_prefix:
        vm_prefix = _opts.vm_prefix.split()

    # Ideally the command line could be communicated directly in an environment
    # variable. However, since environment variables share the same resource
    # space as the command line itself (on Unix at least), this would cause the
    # limit to be exceeded too easily.
    with tempfile.NamedTemporaryFile(suffix='', prefix='mx_subprocess_command.', mode='w', delete=False) as fp:
        subprocessCommandFile = fp.name

        # Don't include the vm_prefix in arguments as this can have unpredictable effects
        args_to_save = args
        if vm_prefix == args[:len(vm_prefix)]:
            args_to_save = args_to_save[len(vm_prefix):]

        for arg in args_to_save:
            # TODO: handle newlines in args once there's a use case
            if '\n' in arg:
                abort('cannot handle new line in argument to run: "' + arg + '"')
            print(arg, file=fp)
    env['MX_SUBPROCESS_COMMAND_FILE'] = subprocessCommandFile

    if _opts.verbose:
        if _opts.very_verbose:
            log('Environment variables:')
            for key in sorted(env.keys()):
                log('    ' + key + '=' + env[key])
            log(' \\\n '.join(map(pipes.quote, args)))
        else:
            if cwd is not None and cwd != _original_directory:
                log('Directory: ' + cwd)
            if env is not None:
                env_diff = [(k, env[k]) for k in env if k not in _original_environ]
                if len(env_diff):
                    log('env ' + ' '.join([n + '=' + pipes.quote(v) for n, v in env_diff]) + ' \\')
            log(' '.join(map(pipes.quote, args)))

    if timeout is None and _opts.ptimeout != 0:
        timeout = _opts.ptimeout

    sub = None

    try:
        if timeout or is_windows():
            preexec_fn, creationflags = _get_new_progress_group_args()
        else:
            preexec_fn, creationflags = (None, 0)

        def redirect(stream, f):
            for line in iter(stream.readline, b''):
                f(_decode(line))
            stream.close()
        stdout = out if not callable(out) else subprocess.PIPE
        stderr = err if not callable(err) else subprocess.PIPE
        stdin_pipe = None if stdin is None else subprocess.PIPE
        p = subprocess.Popen(args, cwd=cwd, stdout=stdout, stderr=stderr, preexec_fn=preexec_fn, creationflags=creationflags, env=env, stdin=stdin_pipe, **kwargs) #pylint: disable=subprocess-popen-preexec-fn
        sub = _addSubprocess(p, args)
        joiners = []
        if callable(out):
            t = Thread(target=redirect, args=(p.stdout, out))
            # Don't make the reader thread a daemon otherwise output can be droppped
            t.start()
            joiners.append(t)
        if callable(err):
            t = Thread(target=redirect, args=(p.stderr, err))
            # Don't make the reader thread a daemon otherwise output can be droppped
            t.start()
            joiners.append(t)
        while any([t.is_alive() for t in joiners]):
            # Need to use timeout otherwise all signals (including CTRL-C) are blocked
            # see: http://bugs.python.org/issue1167930
            for t in joiners:
                t.join(10)
        if isinstance(stdin, str):
            p.stdin.write(stdin)
            p.stdin.close()
        if timeout is None or timeout == 0:
            while True:
                try:
                    retcode = waitOn(p)
                    break
                except KeyboardInterrupt:
                    if is_windows():
                        p.terminate()
                    else:
                        # Propagate SIGINT to subprocess. If the subprocess does not
                        # handle the signal, it will terminate and this loop exits.
                        _kill_process(p.pid, signal.SIGINT)
        else:
            if is_windows():
                abort('Use of timeout not (yet) supported on Windows')
            retcode = _waitWithTimeout(p, args, timeout, nonZeroIsFatal)
    except OSError as e:
        if not nonZeroIsFatal:
            raise e
        abort('Error executing \'' + ' '.join(args) + '\': ' + str(e))
    except KeyboardInterrupt:
        abort(1, killsig=signal.SIGINT)
    finally:
        _removeSubprocess(sub)
        os.remove(subprocessCommandFile)

    if retcode and nonZeroIsFatal:
        if _opts.verbose:
            if _opts.very_verbose:
                raise subprocess.CalledProcessError(retcode, ' '.join(args))
            else:
                log('[exit code: ' + str(retcode) + ']')
        abort(retcode)

    return retcode

def cmd_suffix(name):
    """
    Gets the platform specific suffix for a cmd file
    """
    if is_windows():
        return name + '.cmd'
    return name

def exe_suffix(name):
    """
    Gets the platform specific suffix for an executable
    """
    if is_windows():
        return name + '.exe'
    return name

def add_lib_prefix(name):
    """
    Adds the platform specific library prefix to a name
    """
    if is_darwin() or is_linux() or is_openbsd() or is_sunos():
        return 'lib' + name
    return name

def add_lib_suffix(name):
    """
    Adds the platform specific library suffix to a name
    """
    if is_windows():
        return name + '.dll'
    if is_linux() or is_openbsd() or is_sunos():
        return name + '.so'
    if is_darwin():
        return name + '.dylib'
    return name

def add_debug_lib_suffix(name):
    """
    Adds the platform specific library suffix to a name
    """
    if is_windows():
        return name + '.pdb'
    if is_linux() or is_openbsd() or is_sunos():
        return name + '.debuginfo'
    if is_darwin():
        return name + '.dylib.dSYM'
    return name

mx_subst.results_substitutions.register_with_arg('lib', lambda lib: add_lib_suffix(add_lib_prefix(lib)))
mx_subst.results_substitutions.register_with_arg('libdebug', lambda lib: add_debug_lib_suffix(add_lib_prefix(lib)))
mx_subst.results_substitutions.register_with_arg('libsuffix', add_lib_suffix)
mx_subst.results_substitutions.register_with_arg('cmd', cmd_suffix)
mx_subst.results_substitutions.register_with_arg('exe', exe_suffix)


def get_mxbuild_dir(dependency, **kwargs):
    return dependency.get_output_base()

mx_subst.results_substitutions.register_no_arg('mxbuild', get_mxbuild_dir, keywordArgs=True)

_this_year = str(datetime.now().year)
mx_subst.string_substitutions.register_no_arg('year', lambda: _this_year)


"""
Utility for filtering duplicate lines.
"""
class DuplicateSuppressingStream:
    """
    Creates an object that will suppress duplicate lines sent to `out`.
    The lines considered for suppression are those that contain one of the
    strings in `restrictTo` if it is not None.
    """
    def __init__(self, restrictTo=None, out=sys.stdout):
        self.restrictTo = restrictTo
        self.seen = set()
        self.out = out
        self.currentFilteredLineCount = 0
        self.currentFilteredTime = None

    def isSuppressionCandidate(self, line):
        if self.restrictTo:
            for p in self.restrictTo:
                if p in line:
                    return True
            return False
        else:
            return True

    def write(self, line):
        if self.isSuppressionCandidate(line):
            if line in self.seen:
                self.currentFilteredLineCount += 1
                if self.currentFilteredTime:
                    if time.time() - self.currentFilteredTime > 1 * 60:
                        self.out.write("  Filtered " + str(self.currentFilteredLineCount) + " repeated lines...\n")
                        self.currentFilteredTime = time.time()
                else:
                    self.currentFilteredTime = time.time()
                return
            self.seen.add(line)
        self.currentFilteredLineCount = 0
        self.out.write(line)
        self.currentFilteredTime = None

"""
A JavaCompliance simplifies comparing Java compliance values extracted from a JDK version string.
Example valid version strings and the JDKs they match:
    "8+"       - jdk8, jdk9, jdk10, ...
    "1.8"      - jdk8
    "8..12"    - jdk8, jdk9, jdk10, jdk11, jdk12
    "8,13+"    - jdk8, jdk13, jdk14, ...
    "8..9,13+" - jdk8, jdk9, jdk13, jdk14, ...
There can be at most 2 parts to a version string specifying a non-contiguous range.
The first part of a 2 part version string must have a strict upper bound (i.e. cannot end with "+").
"""
class JavaCompliance(Comparable):
    _version_pattern = re.compile(r'(?:1\.)?(\d+)(.*)')

    @staticmethod
    def _parse(part, ver):
        m = JavaCompliance._version_pattern.match(part)
        if not m:
            abort('not a recognized version string: ' + ver)
        value = int(m.group(1))
        rest = m.group(2)
        if rest.startswith('..'):
            if part.endswith('+'):
                abort('Version range cannot end with "+": ' + part)
            m = JavaCompliance._version_pattern.match(rest[2:])
            if not m:
                abort('not a recognized version string: ' + rest[2:])
            upper_bound = int(m.group(1))
        else:
            upper_bound = value
            if part.endswith('+'):
                upper_bound = None
        return value, upper_bound

    def _bounds(self):
        """
        Gets the bounds for the ranges in the compliance.
        Examples:
           JavaCompliance("8")        -> (8, 8)
           JavaCompliance("8+")       -> (8, None)
           JavaCompliance("8..11")    -> (8, 11)
           JavaCompliance("8,13+")    -> (8, 8, 13, None)
           JavaCompliance("8,13..15") -> (8, 8, 13, 15)
        """
        if self._excluded:
            upper_bound1 = self._excluded[0] - 1
            lower_bound2 = self._excluded[1]
            return (self.value, upper_bound1, lower_bound2, self._upper_bound)
        return (self.value, self._upper_bound)

    def __init__(self, ver):
        ver = str(ver)
        parts = ver.split(',')
        if len(parts) > 1:
            if len(parts) > 2:
                abort('Version string can have at most 2 parts separated by a comma: ' + ver)
            value1, upper_bound1 = JavaCompliance._parse(parts[0], ver)
            value2, upper_bound2 = JavaCompliance._parse(parts[1], ver)
            if upper_bound1 is None:
                abort('First part of 2-part version specification must have an upper bound: ' + ver)
            if value2 <= upper_bound1:
                abort('First part of 2-part version specification must have an upper bound less than lower bound of second part: ' + ver)
            self.value = value1
            self._upper_bound = upper_bound2
            self._excluded = (upper_bound1 + 1, value2)
        else:
            self.value, self._upper_bound = JavaCompliance._parse(parts[0], ver)
            self._excluded = None

    def __str__(self):
        if self.value >= 9:
            return str(self.value)
        return '1.' + str(self.value)

    def __repr__(self):
        bounds = self._bounds()
        if len(bounds) == 4:
            lower1, upper1, lower2, upper2 = bounds
            if lower1 == upper1:
                res = str(lower1)
            else:
                res = '{}..{}'.format(lower1, upper1)
            if upper2 is None:
                return '{},{}+'.format(res, lower2)
            return '{},{}..{}'.format(res, lower2, upper2)
        lower, upper = bounds
        if upper is None:
            return str(lower) + '+'
        if upper == lower:
            return str(lower)
        return str(lower) + '..' + str(upper)

    def __cmp__(self, other):
        if isinstance(other, str):
            other = JavaCompliance(other)
        r = compare(self.value, other.value)
        if r == 0:
            if self._upper_bound is None:
                return 0 if other._upper_bound is None else 1
            if other._upper_bound is None:
                return -1
            r = compare(self._upper_bound, other._upper_bound)
            if r == 0:
                if self._excluded is None:
                    return 0 if other._excluded is None else 1
                if other._excluded is None:
                    return -1
                r = compare(self._excluded, other._excluded)
        return r

    def __contains__(self, other):
        if isinstance(other, str):
            other = JavaCompliance(other)
        assert other._upper_bound is not None, "Contains check cannot be done with version ranges"
        r = compare(self.value, other.value)
        if r == 0:
            return True
        elif r > 0:
            return False
        else: # r < 0
            if self._upper_bound is None:
                return True
            else:
                return compare(self._upper_bound, other.value) >= 0

    def __hash__(self):
        h = self.value ** (self._upper_bound or 1)
        if self._excluded:
            start, stop = self._excluded
            h = hash((h, start, stop))
        return h

    def _is_exact_bound(self):
        return self.value == self._upper_bound

    def _exact_match(self, version):
        assert isinstance(version, VersionSpec)
        if len(version.parts) > 0:
            if len(version.parts) > 1 and version.parts[0] == 1:
                # First part is a '1',  e.g. '1.8.0'.
                value = version.parts[1]
            else:
                # No preceding '1', e.g. '9-ea'. Used for Java 9 early access releases.
                value = version.parts[0]

            if value >= self.value:
                if self._excluded is not None:
                    if value >= self._excluded[0] and value < self._excluded[1]:
                        return False
                if self._upper_bound is not None:
                    return value <= self._upper_bound
                return True
        return False

    def as_version_check(self):
        if self._is_exact_bound():
            versionDesc = str(self)
        elif self._upper_bound is None:
            versionDesc = '>=' + str(self)
        else:
            versionDesc = 'between ' + str(self) + ' and ' + str(self._upper_bound)
        if self._excluded:
            versionDesc = '{} excluding [{}..{})'.format(versionDesc, *self._excluded)
        versionCheck = self._exact_match
        return (versionCheck, versionDesc)

"""
A version specification as defined in JSR-56
"""
class VersionSpec(Comparable):
    def __init__(self, versionString):
        validChar = r'[\x21-\x25\x27-\x29\x2c\x2f-\x5e\x60-\x7f]'
        separator = r'[.\-_]'
        m = re.match("^" + validChar + '+(' + separator + validChar + '+)*$', versionString)
        assert m is not None, 'not a recognized version string: ' + versionString
        self.versionString = versionString
        self.parts = tuple((int(f) if f.isdigit() else f for f in re.split(separator, versionString)))
        i = len(self.parts)
        while i > 0 and self.parts[i - 1] == 0:
            i -= 1
        self.strippedParts = tuple(list(self.parts)[:i])

    def __str__(self):
        return self.versionString

    def __cmp__(self, other):
        return compare(self.strippedParts, other.strippedParts)

    def __hash__(self):
        return self.parts.__hash__()

    def __eq__(self, other):
        return isinstance(other, VersionSpec) and self.strippedParts == other.strippedParts

def _filter_non_existant_paths(paths):
    if paths:
        return os.pathsep.join([path for path in _separatedCygpathW2U(paths).split(os.pathsep) if exists(path)])
    return None


class JDKConfigException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)


def java_debug_args():
    debug_args = []
    attach = None
    if _opts.attach is not None:
        attach = 'server=n,address=' + _opts.attach
    else:
        if _opts.java_dbg_port is not None:
            attach = 'server=y,address=' + str(_opts.java_dbg_port)
    if attach is not None:
        debug_args += ['-Xdebug', '-Xrunjdwp:transport=dt_socket,' + attach + ',suspend=y']
    return debug_args


class JDKConfig(Comparable):
    """
    A JDKConfig object encapsulates info about an installed or deployed JDK.
    """
    def __init__(self, home, tag=None):
        home = realpath(home)
        self.home = home
        self.tag = tag
        self.jar = exe_suffix(join(self.home, 'bin', 'jar'))
        self.java = exe_suffix(join(self.home, 'bin', 'java'))
        self.javac = exe_suffix(join(self.home, 'bin', 'javac'))
        self.javah = exe_suffix(join(self.home, 'bin', 'javah'))
        self.javap = exe_suffix(join(self.home, 'bin', 'javap'))
        self.javadoc = exe_suffix(join(self.home, 'bin', 'javadoc'))
        self.pack200 = exe_suffix(join(self.home, 'bin', 'pack200'))
        self.include_dirs = [join(self.home, 'include'),
                             join(self.home, 'include', 'win32' if is_windows() else get_os())]
        self.toolsjar = join(self.home, 'lib', 'tools.jar')
        if not exists(self.toolsjar):
            self.toolsjar = None
        self._classpaths_initialized = False
        self._bootclasspath = None
        self._extdirs = None
        self._endorseddirs = None
        self._knownJavacLints = None
        self._javacXModuleOptionExists = False

        if not exists(self.java):
            raise JDKConfigException('Java launcher does not exist: ' + self.java)
        if not exists(self.javac):
            raise JDKConfigException('Javac launcher does not exist: ' + self.java)
        if not exists(self.javah):
            # javah is removed as of JDK 10
            self.javah = None

        self.java_args = shlex.split(_opts.java_args) if _opts.java_args else []
        self.java_args_pfx = sum(map(shlex.split, _opts.java_args_pfx), [])
        self.java_args_sfx = sum(map(shlex.split, _opts.java_args_sfx), [])

        # Prepend the -d64 VM option only if the java command supports it
        try:
            output = _check_output_str([self.java, '-d64', '-version'], stderr=subprocess.STDOUT)
            self.java_args = ['-d64'] + self.java_args
        except OSError as e:
            raise JDKConfigException('{}: {}'.format(e.errno, e.strerror))
        except subprocess.CalledProcessError as e:
            try:
                output = _check_output_str([self.java, '-version'], stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                raise JDKConfigException('{}: {}'.format(e.returncode, e.output))

        def _checkOutput(out):
            return 'java version' in out

        # hotspot can print a warning, e.g. if there's a .hotspot_compiler file in the cwd
        output = output.split('\n')
        version = None
        for o in output:
            if _checkOutput(o):
                assert version is None
                version = o

        def _checkOutput0(out):
            return 'version' in out

        # fall back: check for 'version' if there is no 'java version' string
        if not version:
            for o in output:
                if _checkOutput0(o):
                    assert version is None
                    version = o

        self.version = VersionSpec(version.split()[2].strip('"'))
        self.javaCompliance = JavaCompliance(self.version.versionString)

        self.debug_args = java_debug_args()

    def _init_classpaths(self):
        if not self._classpaths_initialized:
            _, binDir = _compile_mx_class('ClasspathDump', jdk=self)
            if self.javaCompliance <= JavaCompliance('1.8'):
                self._bootclasspath, self._extdirs, self._endorseddirs = [x if x != 'null' else None for x in _check_output_str([self.java, '-cp', _cygpathU2W(binDir), 'ClasspathDump'], stderr=subprocess.PIPE).split('|')]
                # All 3 system properties accessed by ClasspathDump are expected to exist
                if not self._bootclasspath or not self._extdirs or not self._endorseddirs:
                    warn("Could not find all classpaths: boot='" + str(self._bootclasspath) + "' extdirs='" + str(self._extdirs) + "' endorseddirs='" + str(self._endorseddirs) + "'")
                self._bootclasspath_unfiltered = self._bootclasspath
                self._bootclasspath = _filter_non_existant_paths(self._bootclasspath)
                self._extdirs = _filter_non_existant_paths(self._extdirs)
                self._endorseddirs = _filter_non_existant_paths(self._endorseddirs)
            else:
                self._bootclasspath = ''
                self._extdirs = None
                self._endorseddirs = None
            self._classpaths_initialized = True

    def __repr__(self):
        return "JDKConfig(" + str(self.home) + ")"

    def __str__(self):
        return "Java " + str(self.version) + " (" + str(self.javaCompliance) + ") from " + str(self.home)

    def __hash__(self):
        return hash(self.home)

    def __cmp__(self, other):
        if other is None:
            return False
        if isinstance(other, JDKConfig):
            compilanceCmp = compare(self.javaCompliance, other.javaCompliance)
            if compilanceCmp:
                return compilanceCmp
            versionCmp = compare(self.version, other.version)
            if versionCmp:
                return versionCmp
            return compare(self.home, other.home)
        raise TypeError()

    def processArgs(self, args, addDefaultArgs=True):
        """
        Returns a list composed of the arguments specified by the -P, -J and -A options (in that order)
        prepended to `args` if `addDefaultArgs` is true otherwise just return `args`.
        """
        def add_debug_args():
            if not self.debug_args or is_debug_disabled():
                return []
            return self.debug_args

        def add_coverage_args(args):
            agent_path = mx_gate.get_jacoco_agent_path()
            if any(arg.startswith('-javaagent') and agent_path in arg for arg in args):
                return []
            # jacoco flags might change in-process -> do not cache
            return mx_gate.get_jacoco_agent_args() or []

        if addDefaultArgs:
            return self.java_args_pfx + self.java_args + add_debug_args() + add_coverage_args(args) + self.java_args_sfx + args
        return args

    def run_java(self, args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, addDefaultArgs=True):
        cmd = [self.java] + self.processArgs(args, addDefaultArgs=addDefaultArgs)
        return run(cmd, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, cwd=cwd, timeout=timeout, env=env)

    def bootclasspath(self, filtered=True):
        """
        Gets the value of the ``sun.boot.class.path`` system property. This will be
        the empty string if this JDK is version 9 or later.

        :param bool filtered: specifies whether to exclude non-existant paths from the returned value
        """
        self._init_classpaths()
        return _separatedCygpathU2W(self._bootclasspath if filtered else self._bootclasspath_unfiltered)

    def javadocLibOptions(self, args):
        """
        Adds javadoc style options for the library paths of this JDK.
        """
        self._init_classpaths()
        if args is None:
            args = []
        if self._bootclasspath:
            args.append('-bootclasspath')
            args.append(_separatedCygpathU2W(self._bootclasspath))
        if self._extdirs:
            args.append('-extdirs')
            args.append(_separatedCygpathU2W(self._extdirs))
        return args

    def javacLibOptions(self, args):
        """
        Adds javac style options for the library paths of this JDK.
        """
        args = self.javadocLibOptions(args)
        if self._endorseddirs:
            args.append('-endorseddirs')
            args.append(_separatedCygpathU2W(self._endorseddirs))
        return args

    def hasJarOnClasspath(self, jar):
        """
        Determines if `jar` is available on the boot class path or in the
        extension/endorsed directories of this JDK.

        :param str jar: jar file name (without directory component)
        :return: the absolute path to the jar file in this JDK matching `jar` or None
        """
        self._init_classpaths()

        if self._bootclasspath:
            for e in self._bootclasspath.split(os.pathsep):
                if basename(e) == jar:
                    return e
        if self._extdirs:
            for d in self._extdirs.split(os.pathsep):
                if len(d) and jar in os.listdir(d):
                    return join(d, jar)
        if self._endorseddirs:
            for d in self._endorseddirs.split(os.pathsep):
                if len(d) and jar in os.listdir(d):
                    return join(d, jar)
        return None

    def getKnownJavacLints(self):
        """
        Gets the lint warnings supported by this JDK.
        """
        if self._knownJavacLints is None:
            try:
                out = _check_output_str([self.javac, '-X'], stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                if e.output:
                    log(e.output)
                raise e
            if self.javaCompliance < JavaCompliance('1.9'):
                lintre = re.compile(r"-Xlint:\{([a-z-]+(?:,[a-z-]+)*)\}")
                m = lintre.search(out)
                if not m:
                    self._knownJavacLints = []
                else:
                    self._knownJavacLints = m.group(1).split(',')
            else:
                self._knownJavacLints = []
                lines = out.split(os.linesep)
                inLintSection = False
                for line in lines:
                    if not inLintSection:
                        if '-Xmodule' in line:
                            self._javacXModuleOptionExists = True
                        elif line.strip() in ['-Xlint:key,...', '-Xlint:<key>(,<key>)*']:
                            inLintSection = True
                    else:
                        if line.startswith('         '):
                            warning = line.split()[0]
                            self._knownJavacLints.append(warning)
                            self._knownJavacLints.append('-' + warning)
                        elif line.strip().startswith('-X'):
                            return self._knownJavacLints
                warn('Did not find lint warnings in output of "javac -X"')
        return self._knownJavacLints

    def get_modules(self):
        """
        Gets the modules in this JDK.

        :return: a list of `JavaModuleDescriptor` objects for modules in this JDK
        :rtype: list
        """
        if self.javaCompliance < '9':
            return []
        if not hasattr(self, '.modules'):
            jdkModules = join(self.home, 'lib', 'modules')
            cache = join(ensure_dir_exists(join(primary_suite().get_output_root(), '.jdk' + str(self.version))), 'listmodules')
            isJDKImage = exists(jdkModules)
            if not exists(cache) or not isJDKImage or TimeStampFile(jdkModules).isNewerThan(cache) or TimeStampFile(__file__).isNewerThan(cache):
                addExportsArg = '--add-exports=java.base/jdk.internal.module=ALL-UNNAMED'
                _, binDir = _compile_mx_class('ListModules', jdk=self, extraJavacArgs=[addExportsArg])
                out = LinesOutputCapture()
                run([self.java, '-cp', _cygpathU2W(binDir), addExportsArg, 'ListModules'], out=out)
                lines = out.lines
                if isJDKImage:
                    try:
                        with open(cache, 'w') as fp:
                            fp.write('\n'.join(lines))
                    except IOError as e:
                        warn('Error writing to ' + cache + ': ' + str(e))
                        os.remove(cache)
            else:
                with open(cache) as fp:
                    lines = fp.read().split('\n')

            modules = {}
            name = None
            requires = {}
            exports = {}
            provides = {}
            uses = set()
            packages = set()
            boot = None

            keyword = lines[0]
            setattr(self, '.transitiveRequiresKeyword', keyword)
            assert keyword in ('transitive', 'public')

            for line in lines[1:]:
                parts = line.strip().split()
                assert len(parts) > 0, '>>>'+line+'<<<'
                if len(parts) == 1:
                    if name is not None:
                        assert name not in modules, 'duplicate module: ' + name
                        modules[name] = JavaModuleDescriptor(name, exports, requires, uses, provides, packages, boot=boot)
                    name = parts[0]
                    requires = {}
                    exports = {}
                    provides = {}
                    uses = set()
                    packages = set()
                    boot = None
                else:
                    assert name, 'cannot parse module descriptor line without module name: ' + line
                    a = parts[0]
                    if a == 'requires':
                        module = parts[-1]
                        modifiers = parts[1:-2] if len(parts) > 2 else []
                        requires[module] = modifiers
                    elif a == 'boot':
                        boot = parts[1] == 'true'
                    elif a == 'exports':
                        source = parts[1]
                        if len(parts) > 2:
                            assert parts[2] == 'to'
                            targets = parts[3:]
                        else:
                            targets = []
                        exports[source] = targets
                    elif a == 'uses':
                        uses.update(parts[1:])
                    elif a == 'package':
                        packages.update(parts[1:])
                    elif a == 'provides':
                        assert len(parts) == 4 and parts[2] == 'with'
                        service = parts[1]
                        provider = parts[3]
                        provides.setdefault(service, []).append(provider)
                    else:
                        abort('Cannot parse module descriptor line: ' + str(parts))
            if name is not None:
                assert name not in modules, 'duplicate module: ' + name
                modules[name] = JavaModuleDescriptor(name, exports, requires, uses, provides, packages, boot=boot)
            setattr(self, '.modules', tuple(modules.values()))
        return getattr(self, '.modules')

    def get_root_modules(self):
        """
        Gets the default set of root modules for the unnamed module.

        From http://openjdk.java.net/jeps/261:

        When the compiler compiles code in the unnamed module, the default set of
        root modules for the unnamed module is computed as follows:

        The java.se module is a root, if it exists. If it does not exist then every
        java.* module on the upgrade module path or among the system modules that
        exports at least one package, without qualification, is a root.

        Every non-java.* module on the upgrade module path or among the system
        modules that exports at least one package, without qualification, is also a root.

        :return: list of JavaModuleDescriptor
        """
        modules = self.get_modules()
        result = [m for m in modules if m.name == 'java.se']
        has_java_dot_se = len(result) != 0
        for mod in modules:
            # no java.se => add all java.*
            if not mod.name.startswith('java.') or not has_java_dot_se:
                if any((len(to) == 0 for _, to in mod.exports.items())):
                    result.append(mod)
        return result

    def get_transitive_requires_keyword(self):
        """
        Gets the keyword used to denote transitive dependencies. This can also effectively
        be used to determine if this is JDK contains the module changes made by
        https://bugs.openjdk.java.net/browse/JDK-8169069.
        """
        if self.javaCompliance < '9':
            abort('Cannot call get_transitive_requires_keyword() for pre-9 JDK ' + str(self))
        self.get_modules()
        # see http://hg.openjdk.java.net/jdk9/hs/jdk/rev/89ef4b822745#l18.37
        return getattr(self, '.transitiveRequiresKeyword')

    def get_automatic_module_name(self, modulejar):
        """
        Derives the name of an automatic module from an automatic module jar according to
        specification of ``java.lang.module.ModuleFinder.of(Path... entries)``.

        :param str modulejar: the path to a jar file treated as an automatic module
        :return: the name of the automatic module derived from `modulejar`
        """

        if self.javaCompliance < '9':
            abort('Cannot call get_transitive_requires_keyword() for pre-9 JDK ' + str(self))

        # Drop directory prefix and .jar (or .zip) suffix
        name = os.path.basename(modulejar)[0:-4]

        # Find first occurrence of -${NUMBER}. or -${NUMBER}$
        m = re.search(r'-(\d+(\.|$))', name)
        if m:
            name = name[0:m.start()]

        # Finally clean up the module name (see jdk.internal.module.ModulePath.cleanModuleName())
        name = re.sub(r'[^A-Za-z0-9]', '.', name) # replace non-alphanumeric
        name = re.sub(r'(\.)(\1)+', '.', name) # collapse repeating dots
        name = re.sub(r'^\.', '', name) # drop leading dots
        return re.sub(r'\.$', '', name) # drop trailing dots

    def get_boot_layer_modules(self):
        """
        Gets the modules in the boot layer of this JDK.

        :return: a list of `JavaModuleDescriptor` objects for boot layer modules in this JDK
        :rtype: list
        """
        return [jmd for jmd in self.get_modules() if jmd.boot]

def check_get_env(key):
    """
    Gets an environment variable, aborting with a useful message if it is not set.
    """
    value = get_env(key)
    if value is None:
        abort('Required environment variable ' + key + ' must be set')
    return value

def get_env(key, default=None):
    """
    Gets an environment variable.
    :param default: default values if the environment variable is not set.
    :type default: str | None
    """
    value = os.getenv(key, default)
    return value

### ~~~~~~~~~~~~~ Logging
def logv(msg=None):
    if vars(_opts).get('verbose') is None:
        def _deferrable():
            logv(msg)
        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.verbose:
        log(msg)

def logvv(msg=None):
    if vars(_opts).get('very_verbose') is None:
        def _deferrable():
            logvv(msg)
        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.very_verbose:
        log(msg)

def log(msg=None):
    """
    Write a message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if vars(_opts).get('quiet'):
        return
    if msg is None:
        print()
    else:
        # https://docs.python.org/2/reference/simple_stmts.html#the-print-statement
        # > A '\n' character is written at the end, unless the print statement
        # > ends with a comma.
        #
        # In CPython, the normal print statement (without comma) is compiled to
        # two bytecode instructions: PRINT_ITEM, followed by PRINT_NEWLINE.
        # Each of these bytecode instructions is executed atomically, but the
        # interpreter can suspend the thread between the two instructions.
        #
        # If the print statement is followed by a comma, the PRINT_NEWLINE
        # instruction is omitted. By manually adding the newline to the string,
        # there is only a single PRINT_ITEM instruction which is executed
        # atomically, but still prints the newline.
        print(str(msg), end='\n')

# https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
_ansi_color_table = {
    'black' : '30',
    'red' : '31',
    'green' : '32',
    'yellow' : '33',
    'blue' : '34',
    'magenta' : '35',
    'cyan' : '36'
    }

def colorize(msg, color='red', bright=True, stream=sys.stderr):
    """
    Wraps `msg` in ANSI escape sequences to make it print to `stream` with foreground font color
    `color` and brightness `bright`. This method returns `msg` unchanged if it is None,
    if it already starts with the designated escape sequence or the execution environment does
    not support color printing on `stream`.
    """
    if msg is None:
        return None
    code = _ansi_color_table.get(color, None)
    if code is None:
        abort('Unsupported color: ' + color + '.\nSupported colors are: ' + ', '.join(_ansi_color_table.keys()))
    if bright:
        code += ';1'
    color_on = '\033[' + code + 'm'
    if not msg.startswith(color_on):
        isUnix = sys.platform.startswith('linux') or sys.platform in ['darwin', 'freebsd']
        if isUnix and hasattr(stream, 'isatty') and stream.isatty():
            return color_on + msg + '\033[0m'
    return msg

def log_error(msg=None):
    """
    Write an error message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if msg is None:
        print(sys.stderr, file=sys.stderr)
    else:
        print(colorize(str(msg), stream=sys.stderr), file=sys.stderr)

### ~~~~~~~~~~~~~ Project

def expand_project_in_class_path_arg(cpArg, jdk=None):
    """
    Replaces each "@" prefixed element in the class path `cpArg` with
    the class path for the dependency named by the element without the "@" prefix.
    """
    if '@' not in cpArg:
        return cpArg
    cp = []
    if jdk is None:
        jdk = get_jdk(tag='default')
    for part in cpArg.split(os.pathsep):
        if part.startswith('@'):
            cp += classpath(part[1:], jdk=jdk).split(os.pathsep)
        else:
            cp.append(part)
    return os.pathsep.join(cp)

def expand_project_in_args(args, insitu=True, jdk=None):
    """
    Looks for the first -cp or -classpath argument in `args` and
    calls expand_project_in_class_path_arg on it. If `insitu` is true,
    then `args` is updated in place otherwise a copy of `args` is modified.
    The updated object is returned.
    """
    for i in range(len(args)):
        if args[i] == '-cp' or args[i] == '-classpath':
            if i + 1 < len(args):
                if not insitu:
                    args = list(args) # clone args
                args[i + 1] = expand_project_in_class_path_arg(args[i + 1], jdk=jdk)
            break
    return args


_flock_cmd = '<uninitialized>'


def flock_cmd():
    global _flock_cmd
    if _flock_cmd == '<uninitialized>':
        out = OutputCapture()
        try:
            flock_ret_code = run(['flock', '--version'], nonZeroIsFatal=False, err=out, out=out)
        except OSError as e:
            flock_ret_code = e
        if flock_ret_code == 0:
            _flock_cmd = 'flock'
        else:
            logvv('Could not find flock command')
            _flock_cmd = None
    return _flock_cmd


_gmake_cmd = '<uninitialized>'


def gmake_cmd():
    global _gmake_cmd
    if _gmake_cmd == '<uninitialized>':
        for a in ['make', 'gmake', 'gnumake']:
            try:
                output = _check_output_str([a, '--version'], stderr=subprocess.STDOUT)
                if 'GNU' in output:
                    _gmake_cmd = a
                    break
            except:
                pass
        if _gmake_cmd == '<uninitialized>':
            abort('Could not find a GNU make executable on the current path.')
    return _gmake_cmd

def expandvars_in_property(value):
    result = expandvars(value)
    if '$' in result or '%' in result:
        abort('Property contains an undefined environment variable: ' + value)
    return result


### ~~~~~~~~~~~~~ commands

# Builtin commands

def _defaultEcjPath():
    jdt = get_env('JDT')
    # Treat empty string the same as undefined
    if jdt:
        return jdt
    return None


def _before_fork():
    try:
        # Try to initialize _scproxy on the main thread to work around issue on macOS:
        # https://bugs.python.org/issue30837
        from _scproxy import _get_proxy_settings, _get_proxies
        _get_proxy_settings()
        _get_proxies()
    except ImportError:
        pass


def build(cmd_args, parser=None):
    """builds the artifacts of one or more dependencies"""

    suppliedParser = parser is not None
    if not suppliedParser:
        parser = ArgumentParser(prog='mx build')

    parser = parser if parser is not None else ArgumentParser(prog='mx build')
    parser.add_argument('-f', action='store_true', dest='force', help='force build (disables timestamp checking)')
    parser.add_argument('-c', action='store_true', dest='clean', help='removes existing build output')
    parallelize = parser.add_mutually_exclusive_group()
    parallelize.add_argument('-n', '--serial', action='store_const', const=False, dest='parallelize', help='serialize Java compilation')
    parallelize.add_argument('-p', action='store_const', const=True, dest='parallelize', help='parallelize Java compilation (default)')
    parser.add_argument('-s', '--shallow-dependency-checks', action='store_const', const=True, help="ignore modification times "
                        "of output files for each of P's dependencies when determining if P should be built. That "
                        "is, only P's sources, suite.py of its suite and whether any of P's dependencies have "
                        "been built are considered. This is useful when an external tool (such as an Eclipse) performs incremental "
                        "compilation that produces finer grained modification times than mx's build system. Shallow "
                        "dependency checking only applies to non-native projects. This option can be also set by defining"
                        "the environment variable MX_BUILD_SHALLOW_DEPENDENCY_CHECKS to true.")
    parser.add_argument('--source', dest='compliance', help='Java compliance level for projects without an explicit one')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--dependencies', '--projects', action='store', help='comma separated dependencies to build (omit to build all dependencies)', metavar='<names>')
    parser.add_argument('--only', action='store', help='comma separated dependencies to build, without checking their dependencies (omit to build all dependencies)')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not build Java projects')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not build native projects')
    parser.add_argument('--no-javac-crosscompile', action='store_false', dest='javac_crosscompile', help="does nothing as cross compilation is no longer supported (preserved for compatibility)")
    parser.add_argument('--warning-as-error', '--jdt-warning-as-error', action='store_true', help='convert all Java compiler warnings to errors')
    parser.add_argument('--force-deprecation-as-warning', action='store_true', help='never treat deprecation warnings as errors irrespective of --warning-as-error')
    parser.add_argument('--force-deprecation-as-warning-for-dependencies', action='store_true', help='never treat deprecation warnings as errors irrespective of --warning-as-error for projects outside of the primary suite')
    parser.add_argument('--jdt-show-task-tags', action='store_true', help='show task tags as Eclipse batch compiler warnings')
    parser.add_argument('--alt-javac', dest='alt_javac', help='path to alternative javac executable', metavar='<path>')
    parser.add_argument('-A', dest='extra_javac_args', action='append', help='pass <flag> directly to Java source compiler', metavar='<flag>', default=[])
    parser.add_argument('--no-daemon', action='store_true', dest='no_daemon', help='disable use of daemon Java compiler (if available)')
    parser.add_argument('--all', action='store_true', help='build all dependencies (not just default targets)')

    compilerSelect = parser.add_mutually_exclusive_group()
    compilerSelect.add_argument('--error-prone', dest='error_prone', help='path to error-prone.jar', metavar='<path>')
    compilerSelect.add_argument('--jdt', help='path to a stand alone Eclipse batch compiler jar (e.g. ecj.jar). ' +
                                'This can also be specified with the JDT environment variable.', default=_defaultEcjPath(), metavar='<path>')
    compilerSelect.add_argument('--force-javac', action='store_true', dest='force_javac', help='use javac even if an Eclipse batch compiler jar is specified')

    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')

    args = parser.parse_args(cmd_args[:])
    deps_w_deprecation_errors = []
    deprecation_as_error_args = args
    if args.force_deprecation_as_warning_for_dependencies:
        args.force_deprecation_as_warning = True
        deprecation_as_error_args = parser.parse_args(cmd_args[:])
        deprecation_as_error_args.force_deprecation_as_warning = False
        primary_java_projects = [p for p in primary_suite().projects if p.isJavaProject()]
        primary_java_project_dists = [d for d in primary_suite().dists if any([p in d.deps for p in primary_java_projects])]
        deps_w_deprecation_errors = [e.name for e in primary_java_projects + primary_java_project_dists]
        logv("Deprecations are only errors for " + ", ".join(deps_w_deprecation_errors))

    if is_windows():
        if args.parallelize:
            warn('parallel builds are not supported on windows: can not use -p')
            args.parallelize = False
    else:
        if args.parallelize is None:
            # Enable parallel compilation by default
            args.parallelize = True

    if not args.force_javac and args.jdt is not None:
        if not args.jdt.endswith('.jar'):
            abort('Path for Eclipse batch compiler does not look like a jar file: ' + args.jdt)
        if not exists(args.jdt):
            abort('Eclipse batch compiler jar does not exist: ' + args.jdt)
        else:
            with zipfile.ZipFile(args.jdt, 'r') as zf:
                if 'org/eclipse/jdt/internal/compiler/apt/' not in zf.namelist():
                    abort('Specified Eclipse compiler does not include annotation processing support. ' +
                          'Ensure you are using a stand alone ecj.jar, not org.eclipse.jdt.core_*.jar ' +
                          'from within the plugins/ directory of an Eclipse IDE installation.')
    onlyDeps = None
    if args.only is not None:
        # N.B. This build will not respect any dependencies (including annotation processor dependencies)
        onlyDeps = set(args.only.split(','))
        roots = [dependency(name) for name in onlyDeps]
    elif args.dependencies is not None:
        if len(args.dependencies) == 0:
            abort('The value of the --dependencies argument cannot be the empty string')
        names = args.dependencies.split(',')
        roots = [dependency(name) for name in names]
    else:
        # This is the normal case for build (e.g. `mx build`) so be
        # clear about JDKs being used ...
        log('JAVA_HOME: ' + get_env('JAVA_HOME', ''))
        if _opts.java_home and _opts.java_home != get_env('JAVA_HOME', ''):
            log('--java-home: ' + _opts.java_home)
        log('EXTRA_JAVA_HOMES: ' + '\n                  '.join(get_env('EXTRA_JAVA_HOMES', '').split(os.pathsep)))
        if _opts.extra_java_homes and _opts.extra_java_homes != get_env('EXTRA_JAVA_HOMES', ''):
            log('--extra-java-homes: ' + '\n                  '.join(_opts.extra_java_homes.split(os.pathsep)))

        # ... and the dependencies that *will not* be built
        if _removedDeps:
            log('Dependencies removed from build:')
            for _, reason in _removedDeps.items():
                if isinstance(reason, tuple):
                    reason, _ = reason
                log(' {}'.format(reason))

        removed, deps = ([], dependencies()) if args.all else defaultDependencies()
        if removed:
            log('Non-default dependencies removed from build (use mx build --all to build them):')
            for d in removed:
                log(' {}'.format(d))

        # Omit all libraries so that only the ones required to build other dependencies are downloaded
        roots = [d for d in deps if not d.isBaseLibrary()]

        if roots:
            roots = _dependencies_opt_limit_to_suites(roots)
            # N.B. Limiting to a suite only affects the starting set of dependencies. Dependencies in other suites will still be built

    sortedTasks = []
    taskMap = {}
    depsMap = {}

    def _createTask(dep, edge):
        if dep.name in deps_w_deprecation_errors:
            task = dep.getBuildTask(deprecation_as_error_args)
        else:
            task = dep.getBuildTask(args)
        if task.subject in taskMap:
            return
        taskMap[dep] = task
        if onlyDeps is None or task.subject.name in onlyDeps:
            sortedTasks.append(task)
        lst = depsMap.setdefault(task.subject, [])
        for d in lst:
            task.deps.append(taskMap[d])

    def _registerDep(src, dst, edge):
        lst = depsMap.setdefault(src, [])
        lst.append(dst)

    walk_deps(visit=_createTask, visitEdge=_registerDep, roots=roots, ignoredEdges=[DEP_EXCLUDED])

    if _opts.very_verbose:
        log("++ Serialized build plan ++")
        for task in sortedTasks:
            if task.deps:
                log(str(task) + " [depends on " + ', '.join([str(t.subject) for t in task.deps]) + ']')
            else:
                log(str(task))
        log("-- Serialized build plan --")

    if len(sortedTasks) == 1:
        # Spinning up a daemon for a single task doesn't make sense
        if not args.no_daemon:
            logv('[Disabling use of compile daemon for single build task]')
            args.no_daemon = True
    daemons = {}
    if args.parallelize and onlyDeps is None:
        _before_fork()
        def joinTasks(tasks):
            failed = []
            for t in tasks:
                t.proc.join()
                _removeSubprocess(t.sub)
                if t.proc.exitcode != 0:
                    failed.append(t)
            return failed

        def checkTasks(tasks):
            active = []
            for t in tasks:
                if t.proc.is_alive():
                    active.append(t)
                else:
                    t.pullSharedMemoryState()
                    t.cleanSharedMemoryState()
                    t._finished = True
                    if t.proc.exitcode != 0:
                        return ([], joinTasks(tasks))
            return (active, [])

        def remainingDepsDepth(task):
            if task._d is None:
                incompleteDeps = [d for d in task.deps if d.proc is None or d.proc.is_alive()]
                if len(incompleteDeps) == 0:
                    task._d = 0
                else:
                    task._d = max([remainingDepsDepth(t) for t in incompleteDeps]) + 1
            return task._d

        def sortWorklist(tasks):
            for t in tasks:
                t._d = None
            return sorted(tasks, key=remainingDepsDepth)

        cpus = cpu_count()
        worklist = sortWorklist(sortedTasks)
        active = []
        failed = []
        def _activeCpus(_active):
            cpus = 0
            for t in _active:
                cpus += t.parallelism
            return cpus

        while len(worklist) != 0:
            while True:
                active, failed = checkTasks(active)
                if len(failed) != 0:
                    assert not active, active
                    break
                if _activeCpus(active) >= cpus:
                    # Sleep for 0.2 second
                    time.sleep(0.2)
                else:
                    break

            if len(failed) != 0:
                break

            def executeTask(task):
                # Clear sub-process list cloned from parent process
                del _currentSubprocesses[:]
                task.execute()
                task.pushSharedMemoryState()

            def depsDone(task):
                for d in task.deps:
                    if d.proc is None or not d._finished:
                        return False
                return True

            added_new_tasks = False
            for task in worklist:
                if depsDone(task) and _activeCpus(active) + task.parallelism <= cpus:
                    worklist.remove(task)
                    task.initSharedMemoryState()
                    task.prepare(daemons)
                    task.proc = multiprocessing.Process(target=executeTask, args=(task,))
                    task._finished = False
                    task.proc.start()
                    active.append(task)
                    task.sub = _addSubprocess(task.proc, [str(task)])
                    added_new_tasks = True
                if _activeCpus(active) >= cpus:
                    break

            if not added_new_tasks:
                time.sleep(0.2)

            worklist = sortWorklist(worklist)

        failed += joinTasks(active)

        if len(failed):
            for t in failed:
                log_error('{0} failed'.format(t))
            for daemon in daemons.values():
                daemon.shutdown()
            abort('{0} build tasks failed'.format(len(failed)))

    else:  # not parallelize
        for t in sortedTasks:
            t.prepare(daemons)
            t.execute()

    for daemon in daemons.values():
        daemon.shutdown()

    # TODO check for distributions overlap (while loading suites?)

    if suppliedParser:
        return args
    return None

def build_suite(s):
    """build all projects in suite (for dynamic import)"""
    # Note we must use the "build" method in "s" and not the one
    # in the dict. If there isn't one we use mx.build
    project_names = [p.name for p in s.projects]
    if hasattr(s.extensions, 'build'):
        build_command = s.extensions.build
    else:
        build_command = build
    build_command(['--dependencies', ','.join(project_names)])

def _chunk_files_for_command_line(files, limit=None, separator=' ', pathFunction=lambda f: f):
    """
    Gets a generator for splitting up a list of files into chunks such that the
    size of the `separator` separated file paths in a chunk is less than `limit`.
    This is used to work around system command line length limits.

    :param list files: list of files to chunk
    :param int limit: the maximum number of characters in a chunk. If None, then a limit is derived from host OS limits.
    :param str separator: the separator between each file path on the command line
    :param pathFunction: a function for converting each entry in `files` to a path name
    :return: a generator yielding the list of files in each chunk
    """
    chunkSize = 0
    chunkStart = 0
    if limit is None:
        if is_windows():
            # The CreateProcess function on Windows limits the length of a command line to
            # 32,768 characters (http://msdn.microsoft.com/en-us/library/ms682425%28VS.85%29.aspx)
            limit = 32768
        else:
            limit = os.sysconf('SC_ARG_MAX')
            if limit == -1:
                limit = 262144 # we could use sys.maxint but we prefer a more robust smaller value
        # Reduce the limit by 20% to account for the space required by environment
        # variables and other things that use up the command line limit.
        # This is not an exact calculation as calculating the exact requirements
        # is complex (https://www.in-ulm.de/~mascheck/various/argmax/)
        limit = limit * 0.8
    for i in range(len(files)):
        path = pathFunction(files[i])
        size = len(path) + len(separator)
        assert size < limit
        if chunkSize + size < limit:
            chunkSize += size
        else:
            assert i > chunkStart
            yield files[chunkStart:i]
            chunkStart = i
            chunkSize = 0
    if chunkStart == 0:
        assert chunkSize < limit
        yield files
    elif chunkStart < len(files):
        yield files[chunkStart:]

def eclipseformat(args):
    """run the Eclipse Code Formatter on the Java sources

    The exit code 1 denotes that at least one file was modified."""

    parser = ArgumentParser(prog='mx eclipseformat')
    parser.add_argument('-e', '--eclipse-exe', help='location of the Eclipse executable')
    parser.add_argument('-C', '--no-backup', action='store_false', dest='backup', help='do not save backup of modified files')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    parser.add_argument('--patchfile', type=FileType("w"), help='file to which a patch denoting the applied formatting changes is written')
    parser.add_argument('--restore', action='store_true', help='restore original files after the formatting job (does not create a backup).')

    args = parser.parse_args(args)
    if args.eclipse_exe is None:
        args.eclipse_exe = os.environ.get('ECLIPSE_EXE')
    if args.eclipse_exe is None:
        abort('Could not find Eclipse executable. Use -e option or ensure ECLIPSE_EXE environment variable is set.')
    if args.restore:
        args.backup = False

    # Maybe an Eclipse installation dir was specified - look for the executable in it
    if isdir(args.eclipse_exe):
        args.eclipse_exe = join(args.eclipse_exe, exe_suffix('eclipse'))
        warn("The eclipse-exe was a directory, now using " + args.eclipse_exe)

    if not os.path.isfile(args.eclipse_exe):
        abort('File does not exist: ' + args.eclipse_exe)
    if not os.access(args.eclipse_exe, os.X_OK):
        abort('Not an executable file: ' + args.eclipse_exe)

    wsroot = eclipseinit([], buildProcessorJars=False, doFsckProjects=False)

    # build list of projects to be processed
    if args.projects is not None:
        projectsToProcess = [project(name) for name in args.projects.split(',')]
    elif args.primary:
        projectsToProcess = projects(limit_to_primary=True)
    else:
        projectsToProcess = projects(opt_limit_to_suite=True)

    class Batch:
        def __init__(self, settingsDir):
            self.path = join(settingsDir, 'org.eclipse.jdt.core.prefs')
            with open(join(settingsDir, 'org.eclipse.jdt.ui.prefs')) as fp:
                jdtUiPrefs = fp.read()
            self.removeTrailingWhitespace = 'sp_cleanup.remove_trailing_whitespaces_all=true' in jdtUiPrefs
            if self.removeTrailingWhitespace:
                assert 'sp_cleanup.remove_trailing_whitespaces=true' in jdtUiPrefs and 'sp_cleanup.remove_trailing_whitespaces_ignore_empty=false' in jdtUiPrefs
            self.cachedHash = None

        def __hash__(self):
            if not self.cachedHash:
                with open(self.path) as fp:
                    self.cachedHash = (fp.read(), self.removeTrailingWhitespace).__hash__()
            return self.cachedHash

        def __eq__(self, other):
            if not isinstance(other, Batch):
                return False
            if self.removeTrailingWhitespace != other.removeTrailingWhitespace:
                return False
            if self.path == other.path:
                return True
            with open(self.path) as fp:
                with open(other.path) as ofp:
                    if fp.read() != ofp.read():
                        return False
            return True


    class FileInfo:
        def __init__(self, path):
            self.path = path
            with open(path) as fp:
                self.content = fp.read()
            self.times = (os.path.getatime(path), getmtime(path))

        def update(self, removeTrailingWhitespace, restore):
            with open(self.path) as fp:
                content = fp.read()
            file_modified = False  # whether the file was modified by formatting
            file_updated = False  # whether the file is really different on disk after the update
            if self.content != content:
                # Only apply *after* formatting to match the order in which the IDE does it
                if removeTrailingWhitespace:
                    content, n = re.subn(r'[ \t]+$', '', content, flags=re.MULTILINE)
                    if n != 0 and self.content == content:
                        # undo on-disk changes made by the Eclipse formatter
                        with open(self.path, 'w') as fp:
                            fp.write(content)

                if self.content != content:
                    rpath = os.path.relpath(self.path, primary_suite().dir)
                    self.diff = difflib.unified_diff(self.content.splitlines(1), content.splitlines(1), fromfile=join('a', rpath), tofile=join('b', rpath))
                    if restore:
                        with open(self.path, 'w') as fp:
                            fp.write(self.content)
                    else:
                        file_updated = True
                        self.content = content
                    file_modified = True

            if not file_updated and (os.path.getatime(self.path), getmtime(self.path)) != self.times:
                # reset access and modification time of file
                os.utime(self.path, self.times)
            return file_modified

    modified = list()
    batches = dict()  # all sources with the same formatting settings are formatted together
    for p in projectsToProcess:
        if not p.isJavaProject():
            continue
        sourceDirs = p.source_dirs()

        batch = Batch(join(p.dir, '.settings'))

        if not exists(batch.path):
            if _opts.verbose:
                log('[no Eclipse Code Formatter preferences at {0} - skipping]'.format(batch.path))
            continue

        javafiles = []
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                for f in [join(root, name) for name in files if name.endswith('.java')]:
                    javafiles.append(FileInfo(f))
        if len(javafiles) == 0:
            logv('[no Java sources in {0} - skipping]'.format(p.name))
            continue

        res = batches.setdefault(batch, javafiles)
        if res is not javafiles:
            res.extend(javafiles)

    log("we have: " + str(len(batches)) + " batches")
    batch_num = 0
    for batch, javafiles in batches.items():
        batch_num += 1
        log("Processing batch {0} ({1} files)...".format(batch_num, len(javafiles)))

        jdk = get_jdk()

        for chunk in _chunk_files_for_command_line(javafiles, pathFunction=lambda f: f.path):
            capture = OutputCapture()
            rc = run([args.eclipse_exe,
                '-nosplash',
                '-application',
                '-consolelog',
                '-data', wsroot,
                '-vm', jdk.java,
                'org.eclipse.jdt.core.JavaCodeFormatter',
                '-config', batch.path]
                + [f.path for f in chunk], out=capture, err=capture, nonZeroIsFatal=False)
            if rc != 0:
                log(capture.data)
                abort("Error while running formatter")
            for fi in chunk:
                if fi.update(batch.removeTrailingWhitespace, args.restore):
                    modified.append(fi)

    log('{0} files were modified'.format(len(modified)))

    if len(modified) != 0:
        arcbase = primary_suite().dir
        if args.backup:
            backup = os.path.abspath('eclipseformat.backup.zip')
            zf = zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED)
        for fi in modified:
            diffs = ''.join(fi.diff)
            if args.patchfile:
                args.patchfile.write(diffs)
            name = os.path.relpath(fi.path, arcbase)
            log(' - {0}'.format(name))
            log('Changes:')
            log(diffs)
            if args.backup:
                arcname = name.replace(os.sep, '/')
                zf.writestr(arcname, fi.content)
        if args.backup:
            zf.close()
            log('Wrote backup of {0} modified files to {1}'.format(len(modified), backup))
        if args.patchfile:
            log('Wrote patches to {0}'.format(args.patchfile.name))
            args.patchfile.close()
        return 1
    return 0

def processorjars():
    for s in suites(True):
        _processorjars_suite(s)

def _processorjars_suite(s):
    """
    Builds all distributions in this suite that define one or more annotation processors.
    Returns the jar files for the built distributions.
    """
    apDists = [d for d in s.dists if d.isJARDistribution() and d.definedAnnotationProcessors]
    if not apDists:
        return []

    names = [ap.name for ap in apDists]
    build(['--dependencies', ",".join(names)])
    return [ap.path for ap in apDists]

pylint_ver_map = {
    (1, 1): {
        'rcfile': '.pylintrc11',
        'additional_options': []
    },
    (1, 9): {
        'rcfile': '.pylintrc19',
        'additional_options': ['--score=n']
    },
    (2, 2): {
        'rcfile': '.pylintrc22',
        'additional_options': ['--score=n']
    }
}

@no_suite_loading
def pylint(args):
    """run pylint (if available) over Python source files (found by '<vc> locate' or by tree walk with -walk)"""

    parser = ArgumentParser(prog='mx pylint')
    _add_command_primary_option(parser)
    parser.add_argument('--walk', action='store_true', help='use tree walk find .py files')
    parser.add_argument('--all', action='store_true', help='check all files, not just files in the mx.* directory.')
    args = parser.parse_args(args)
    ver = (-1, -1)

    pylint_exe = None
    output = None
    exc = None
    for candidate in ['pylint2', 'pylint-2', 'pylint']:
        try:
            output = _check_output_str([candidate, '--version'], stderr=subprocess.STDOUT)
            pylint_exe = candidate
            break
        except OSError as e:
            exc = e
    else:
        log_error('pylint is not available: ' + str(exc))
        return -1

    m = re.search(r'^pylint-?2? (\d+)\.(\d+)\.(\d+),', output, re.MULTILINE)
    if not m:
        log_error('could not determine pylint version from ' + output)
        return -1
    major, minor, micro = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    log("Detected pylint version: {0}.{1}.{2}".format(major, minor, micro))
    ver = (major, minor)
    if ver not in pylint_ver_map:
        log_error('pylint version must be one of {3} (got {0}.{1}.{2})'.format(major, minor, micro, pylint_ver_map.keys()))
        return -1

    rcfile = join(dirname(__file__), pylint_ver_map[ver]['rcfile'])
    if not exists(rcfile):
        log_error('pylint configuration file does not exist: ' + rcfile)
        return -1

    additional_options = pylint_ver_map[ver]['additional_options']

    def findfiles_by_walk(pyfiles):
        for suite in suites(True, includeBinary=False):
            if args.primary and not suite.primary:
                continue
            for root, dirs, files in os.walk(suite.dir if args.all else suite.mxDir):
                for f in files:
                    if f.endswith('.py'):
                        pyfile = join(root, f)
                        pyfiles.append(pyfile)
                if 'bin' in dirs:
                    dirs.remove('bin')
                if 'lib' in dirs:
                    # avoids downloaded .py files
                    dirs.remove('lib')

    def findfiles_by_vc(pyfiles):
        for suite in suites(True, includeBinary=False):
            if args.primary and not suite.primary:
                continue
            suite_location = os.path.relpath(suite.dir if args.all else suite.mxDir, suite.vc_dir)
            files = suite.vc.locate(suite.vc_dir, [join(suite_location, '**.py')])
            compat = suite.getMxCompatibility()
            if compat.makePylintVCInputsAbsolute():
                files = [join(suite.vc_dir, f) for f in files]
            for pyfile in files:
                if exists(pyfile):
                    pyfiles.append(pyfile)

    pyfiles = []

    # Process mxtool's own py files only if mx is the primary suite
    if primary_suite() is _mx_suite:
        for root, _, files in os.walk(dirname(__file__)):
            for f in files:
                if f.endswith('.py'):
                    pyfile = join(root, f)
                    pyfiles.append(pyfile)
    else:
        if args.walk:
            findfiles_by_walk(pyfiles)
        else:
            findfiles_by_vc(pyfiles)

    env = os.environ.copy()

    pythonpath = dirname(__file__)
    for suite in suites(True):
        pythonpath = os.pathsep.join([pythonpath, suite.mxDir])

    env['PYTHONPATH'] = pythonpath

    for pyfile in pyfiles:
        log('Running pylint on ' + pyfile + '...')
        run([pylint_exe, '--reports=n', '--rcfile=' + rcfile, pyfile] + additional_options, env=env)

    return 0


class NoOpContext(object):
    def __init__(self, value=None):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class TempDir(object):
    def __init__(self, parent_dir=None):
        self.parent_dir = parent_dir

    def __enter__(self):
        self.tmp_dir = mkdtemp(dir=self.parent_dir)
        return self.tmp_dir

    def __exit__(self, exc_type, exc_value, traceback):
        shutil.rmtree(self.tmp_dir)


class TempDirCwd(TempDir):
    def __init__(self, parent_dir=None): #pylint: disable=useless-super-delegation
        super(TempDirCwd, self).__init__(parent_dir)

    def __enter__(self):
        super(TempDirCwd, self).__enter__()
        self.prev_dir = os.getcwd()
        os.chdir(self.tmp_dir)
        return self.tmp_dir

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.prev_dir)
        super(TempDirCwd, self).__exit__(exc_type, exc_value, traceback)


class SafeFileCreation(object):
    """
    Context manager for creating a file that tries hard to handle races between processes/threads
    creating the same file. It tries to ensure that the file is created with the content provided
    by exactly one process/thread but makes no guarantee about which process/thread wins.

    Note that truly atomic file copying is hard (http://stackoverflow.com/a/28090883/6691595)

    :Example:

    with SafeFileCreation(dst) as sfc:
        shutil.copy(src, sfc.tmpPath)

    """
    def __init__(self, path, companion_patterns=None):
        self.path = path
        self.companion_patterns = companion_patterns or []

    def __enter__(self):
        if self.path is not None:
            path_dir = dirname(self.path)
            ensure_dir_exists(path_dir)
            # Temporary file must be on the same file system as self.path for os.rename to be atomic.
            fd, tmp = tempfile.mkstemp(suffix=basename(self.path), dir=path_dir)
            self.tmpFd = fd
            self.tmpPath = tmp
        else:
            self.tmpFd = None
            self.tmpPath = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.path is None:
            return
        # Windows will complain about tmp being in use by another process
        # when calling os.rename if we don't close the file descriptor.
        os.close(self.tmpFd)

        def _handle_file(tmpPath, path):
            if exists(tmpPath):
                if exc_value:
                    # If an error occurred, delete the temp file
                    # instead of renaming it
                    os.remove(tmpPath)
                else:
                    # Correct the permissions on the temporary file which is created with restrictive permissions
                    os.chmod(tmpPath, 0o666 & ~currentUmask)
                    # Atomic if self.path does not already exist.
                    if is_windows() and exists(path):
                        # Needed on Windows
                        os.remove(path)
                    os.rename(tmpPath, path)
        _handle_file(self.tmpPath, self.path)
        for companion_pattern in self.companion_patterns:
            _handle_file(companion_pattern.format(path=self.tmpPath), companion_pattern.format(path=self.path))


class Archiver(SafeFileCreation):
    """
    Utility for creating and updating a zip or tar file atomically.
    """
    def __init__(self, path, kind='zip', reset_user_group=False, duplicates_action=None, context=None, compress=False):
        SafeFileCreation.__init__(self, path)
        self.kind = kind
        self.zf = None
        self._add_f = None
        self._add_str = None
        self._add_link = None
        self.reset_user_group = reset_user_group
        self.compress = compress
        assert duplicates_action in [None, 'warn', 'abort']
        self.duplicates_action = duplicates_action
        self._provenance_map = {} if duplicates_action else None
        self.context = context

    def _add_zip(self, filename, archive_name, provenance):
        self._add_provenance(archive_name, provenance)
        self.zf.write(filename, archive_name)

    def _add_str_zip(self, data, archive_name, provenance):
        self._add_provenance(archive_name, provenance)
        self.zf.writestr(archive_name, data)

    def _add_link_zip(self, target, archive_name, provenance):
        abort("Can not add symlinks in ZIP archives!", context=self.context)

    def _add_tar(self, filename, archive_name, provenance):
        self._add_provenance(archive_name, provenance)
        self.zf.add(filename, archive_name, filter=self._tarinfo_filter, recursive=False)

    def _add_str_tar(self, data, archive_name, provenance):
        self._add_provenance(archive_name, provenance)
        tarinfo = self.zf.tarinfo()
        tarinfo.name = archive_name
        tarinfo.size = len(data)
        tarinfo.mtime = calendar.timegm(datetime.now().utctimetuple())
        self.zf.addfile(self._tarinfo_filter(tarinfo), StringIO(data))

    def _add_link_tar(self, target, archive_name, provenance):
        self._add_provenance(archive_name, provenance)
        tarinfo = self.zf.tarinfo()
        tarinfo.name = archive_name
        tarinfo.type = tarfile.SYMTYPE
        tarinfo.linkname = target
        tarinfo.mtime = calendar.timegm(datetime.now().utctimetuple())
        self.zf.addfile(self._tarinfo_filter(tarinfo))

    def _tarinfo_filter(self, tarinfo):
        if self.reset_user_group:
            tarinfo.uid = tarinfo.gid = 0
            tarinfo.uname = tarinfo.gname = "root"
        return tarinfo

    def _add_provenance(self, archive_name, provenance):
        if self._provenance_map is None:
            return
        if archive_name in self._provenance_map:
            msg = "Duplicate archive entry: '{}'".format(archive_name)
            old_provenance = self._provenance_map[archive_name]
            if old_provenance:
                msg += " previously added by " + old_provenance
            if provenance:
                msg += " added again by " + provenance
            abort_or_warn(msg, self.duplicates_action == 'abort', context=self.context)
        self._provenance_map[archive_name] = provenance

    def __enter__(self):
        if self.path:
            SafeFileCreation.__enter__(self)
            if self.kind == 'zip' or self.kind == 'jar':
                self.zf = zipfile.ZipFile(self.tmpPath, 'w', compression=zipfile.ZIP_DEFLATED if self.compress else zipfile.ZIP_STORED)
                self._add_f = self._add_zip
                self._add_str = self._add_str_zip
                self._add_link = self._add_link_zip
            elif self.kind == 'tar':
                if self.compress:
                    warn("Archiver created with compress=True and kind=tar, ignoring compression setting")
                self.zf = tarfile.open(self.tmpPath, 'w')
                self._add_f = self._add_tar
                self._add_str = self._add_str_tar
                self._add_link = self._add_link_tar
            elif self.kind == 'tgz':
                if self.compress:
                    warn("Archiver created with compress=False and kind=tgz, ignoring compression setting")
                self.zf = tarfile.open(self.tmpPath, 'w:gz')
                self._add_f = self._add_tar
                self._add_str = self._add_str_tar
                self._add_link = self._add_link_tar
            else:
                abort('unsupported archive kind: ' + self.kind, context=self.context)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.path:
            if self.zf:
                self.zf.close()
            SafeFileCreation.__exit__(self, exc_type, exc_value, traceback)

    def add(self, filename, archive_name, provenance):
        self._add_f(filename, archive_name, provenance)

    def add_str(self, data, archive_name, provenance):
        self._add_str(data, archive_name, provenance)

    def add_link(self, target, archive_name, provenance):
        self._add_link(target, archive_name, provenance)

def _unstrip(args):
    """use stripping mappings of a file to unstrip the contents of another file

    Arguments are mapping file and content file.
    Directly passes the arguments to proguard-retrace.jar. For more details see: http://proguard.sourceforge.net/manual/retrace/usage.html"""
    unstrip(args)
    return 0

def unstrip(args):
    proguard_cp = library('PROGUARD_RETRACE_6_0_3').get_path(resolve=True) + os.pathsep + library('PROGUARD_6_0_3').get_path(resolve=True)
    unstrip_command = ['-cp', proguard_cp, 'proguard.retrace.ReTrace']
    mapfiles = []
    inputfiles = []
    for arg in args:
        if os.path.isdir(arg):
            mapfiles += glob.glob(join(arg, '*' + JARDistribution._strip_map_file_suffix))
        elif arg.endswith(JARDistribution._strip_map_file_suffix):
            mapfiles.append(arg)
        else:
            inputfiles.append(arg)
    with tempfile.NamedTemporaryFile() as catmapfile:
        _merge_file_contents(mapfiles, catmapfile)
        run_java(unstrip_command + [catmapfile.name] + inputfiles)

def _archive(args):
    """create jar files for projects and distributions"""
    archive(args)
    return 0

def archive(args):
    parser = ArgumentParser(prog='mx archive')
    parser.add_argument('--parsable', action='store_true', dest='parsable', help='Outputs results in a stable parsable way (one archive per line, <ARCHIVE>=<path>)')
    parser.add_argument('names', nargs=REMAINDER, metavar='[<project>|@<distribution>]...')
    args = parser.parse_args(args)

    archives = []
    for name in args.names:
        if name.startswith('@'):
            dname = name[1:]
            d = distribution(dname)
            if isinstance(d.suite, BinarySuite):
                abort('Cannot re-build archive for distribution {} from binary suite {}'.format(dname, d.suite.name))
            d.make_archive()
            archives.append(d.path)
            if args.parsable:
                print('{0}={1}'.format(dname, d.path))
        else:
            p = project(name)
            path = p.make_archive()
            archives.append(path)
            if args.parsable:
                print('{0}={1}'.format(name, path))

    if not args.parsable:
        logv("generated archives: " + str(archives))
    return archives

def checkoverlap(args):
    """check all distributions for overlap

    The exit code of this command reflects how many projects are included in more than one distribution."""

    projToDist = {}
    for d in sorted_dists():
        if d.internal:
            continue
        for p in d.archived_deps():
            if p.isProject():
                if p in projToDist:
                    projToDist[p].append(d)
                else:
                    projToDist[p] = [d]

    count = 0
    for p in projToDist:
        ds = projToDist[p]
        if len(ds) > 1:
            remove = []
            for d in ds:
                overlaps = d.overlapped_distributions()
                if len([o for o in ds if o in overlaps]) != 0:
                    remove.append(d)
            ds = [d for d in ds if d not in remove]
            if len(ds) > 1:
                print('{} is in more than one distribution: {}'.format(p, [d.name for d in ds]))
                count += 1
    return count

def canonicalizeprojects(args):
    """check all project specifications for canonical dependencies

    The exit code of this command reflects how many projects have non-canonical dependencies."""

    nonCanonical = []
    for s in suites(True, includeBinary=False):
        for p in (p for p in s.projects if p.isJavaProject()):
            if p.suite.getMxCompatibility().check_package_locations():
                for source, package in p.mismatched_imports().items():
                    if package:
                        p.abort('{} declares a package that does not match its location: {}'.format(source, package))
                    else:
                        p.abort('{} does not declares a package to match its location'.format(source))
            if p.is_test_project():
                continue
            if p.checkPackagePrefix:
                for pkg in p.defined_java_packages():
                    if not pkg.startswith(p.name):
                        p.abort('package in {0} does not have prefix matching project name: {1}'.format(p, pkg))

            ignoredDeps = {d for d in p.deps if d.isJavaProject()}
            for pkg in p.imported_java_packages():
                for dep in p.deps:
                    if not dep.isJavaProject():
                        ignoredDeps.discard(dep)
                    else:
                        if pkg in dep.defined_java_packages():
                            ignoredDeps.discard(dep)
                        if pkg in dep.extended_java_packages():
                            ignoredDeps.discard(dep)

            genDeps = frozenset([dependency(name, context=p) for name in getattr(p, "generatedDependencies", [])])
            incorrectGenDeps = genDeps - ignoredDeps
            ignoredDeps -= genDeps
            if incorrectGenDeps:
                p.abort('{0} should declare following as normal dependencies, not generatedDependencies: {1}'.format(p, ', '.join([d.name for d in incorrectGenDeps])))

            if len(ignoredDeps) != 0:
                candidates = set()
                # Compute candidate dependencies based on projects required by p
                for d in dependencies():
                    if d.isJavaProject() and not d.defined_java_packages().isdisjoint(p.imported_java_packages()):
                        candidates.add(d)
                # Remove non-canonical candidates
                for c in list(candidates):
                    c.walk_deps(visit=lambda dep, edge: candidates.discard(dep) if dep.isJavaProject() else None)
                candidates = [d.name for d in candidates]

                msg = 'Non-generated source code in {0} does not use any packages defined in these projects: {1}\nIf the above projects are only ' \
                        'used in generated sources, declare them in a "generatedDependencies" attribute of {0}.\nComputed project dependencies: {2}'
                p.abort(msg.format(
                    p, ', '.join([d.name for d in ignoredDeps]), ','.join(candidates)))

            excess = frozenset([d for d in p.deps if d.isJavaProject()]) - set(p.canonical_deps())
            if len(excess) != 0:
                nonCanonical.append(p)
        for d in s.dists:
            different_test_status = [pp for pp in d.archived_deps() if pp.isProject() and pp.is_test_project() != d.is_test_distribution()]
            if different_test_status:
                project_list_str = '\n'.join((' - ' + pp.name for pp in different_test_status))
                should_abort = d.suite.getMxCompatibility().enforceTestDistributions()
                if d.is_test_distribution():
                    abort_or_warn("{} is a test distribution but it contains non-test projects:\n{}".format(d.name, project_list_str), should_abort)
                else:
                    abort_or_warn("{} is not a test distribution but it contains test projects:\n{}".format(d.name, project_list_str), should_abort)
    if len(nonCanonical) != 0:
        for p in nonCanonical:
            canonicalDeps = p.canonical_deps()
            if len(canonicalDeps) != 0:
                log(p.__abort_context__() + ':\nCanonical dependencies for project ' + p.name + ' are: [')
                for d in canonicalDeps:
                    name = d.suite.name + ':' + d.name if d.suite is not p.suite else d.name
                    log('        "' + name + '",')
                log('      ],')
            else:
                log(p.__abort_context__() + ':\nCanonical dependencies for project ' + p.name + ' are: []')
    return len(nonCanonical)


"""
Represents a file and its modification time stamp at the time the TimeStampFile is created.
"""
class TimeStampFile:
    def __init__(self, path, followSymlinks=True):
        """
        :type path: str
        :type followSymlinks: bool | str
        """
        assert isinstance(path, str), path + ' # type=' + str(type(path))
        self.path = path
        if exists(path):
            if followSymlinks == 'newest':
                self.timestamp = max(getmtime(path), lstat(path).st_mtime)
            elif followSymlinks:
                self.timestamp = getmtime(path)
            else:
                self.timestamp = lstat(path).st_mtime
        else:
            self.timestamp = None

    @staticmethod
    def newest(paths):
        """
        Creates a TimeStampFile for the file in `paths` with the most recent modification time.
        Entries in `paths` that do not correspond to an existing file are ignored.
        """
        ts = None
        for path in paths:
            if exists(path):
                if not ts:
                    ts = TimeStampFile(path)
                elif ts.isOlderThan(path):
                    ts = TimeStampFile(path)
        return ts

    def isOlderThan(self, arg):
        if not self.timestamp:
            return True
        if isinstance(arg, (int, float)):
            return self.timestamp < arg
        if isinstance(arg, TimeStampFile):
            if arg.timestamp is None:
                return False
            else:
                return arg.timestamp > self.timestamp
        elif isinstance(arg, list):
            files = arg
        else:
            files = [arg]
        for f in files:
            if not os.path.exists(f):
                return True
            if getmtime(f) > self.timestamp:
                return True
        return False

    def isNewerThan(self, arg):
        if not self.timestamp:
            return False
        if isinstance(arg, (int, float)):
            return self.timestamp > arg
        if isinstance(arg, TimeStampFile):
            if arg.timestamp is None:
                return False
            else:
                return arg.timestamp < self.timestamp
        elif isinstance(arg, list):
            files = arg
        else:
            files = [arg]
        for f in files:
            if getmtime(f) < self.timestamp:
                return True
        return False

    def exists(self):
        return exists(self.path)

    def __str__(self):
        if self.timestamp:
            ts = time.strftime('[%Y-%m-%d %H:%M:%S]', time.localtime(self.timestamp))
        else:
            ts = '[does not exist]'
        return self.path + ts

    def touch(self):
        if exists(self.path):
            os.utime(self.path, None)
        else:
            ensure_dir_exists(dirname(self.path))
            open(self.path, 'a')
        self.timestamp = getmtime(self.path)

### ~~~~~~~~~~~~~ commands

def checkstyle(args):
    """run Checkstyle on the Java sources

   Run Checkstyle over the Java sources. Any errors or warnings
   produced by Checkstyle result in a non-zero exit code."""

    parser = ArgumentParser(prog='mx checkstyle')

    parser.add_argument('-f', action='store_true', dest='force', help='force checking (disables timestamp checking)')
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    args = parser.parse_args(args)

    totalErrors = 0

    class Batch:
        def __init__(self, config, suite):
            self.suite = suite
            config_relative_to_root = os.path.relpath(os.path.abspath(config), os.sep)
            self.timestamp = TimeStampFile(join(suite.get_mx_output_dir(), 'checkstyle-timestamps',
                                                config_relative_to_root + '.timestamp'))
            self.sources = []
            self.projects = []

    batches = {}
    for p in projects(opt_limit_to_suite=True):
        if not p.isJavaProject():
            continue
        if args.primary and not p.suite.primary:
            continue
        sourceDirs = p.source_dirs()

        config, checkstyleVersion, _ = p.get_checkstyle_config()
        if not config:
            logv('[No Checkstyle configuration found for {0} - skipping]'.format(p))
            continue

        # skip checking this Java project if its Java compliance level is "higher" than the configured JDK
        jdk = get_jdk(p.javaCompliance)
        assert jdk

        key = (config, checkstyleVersion)
        batch = batches.setdefault(key, Batch(config, p.suite))
        batch.projects.append(p)

        for sourceDir in sourceDirs:
            javafilelist = []
            for root, _, files in os.walk(sourceDir):
                javafilelist += [join(root, name) for name in files if name.endswith('.java') and name != 'package-info.java']
            if len(javafilelist) == 0:
                logv('[no Java sources in {0} - skipping]'.format(sourceDir))
                continue

            mustCheck = False
            if not args.force and batch.timestamp.exists():
                mustCheck = batch.timestamp.isOlderThan(javafilelist)
            else:
                mustCheck = True

            if not mustCheck:
                if _opts.verbose:
                    log('[all Java sources in {0} already checked - skipping]'.format(sourceDir))
                continue

            exclude = join(p.dir, '.checkstyle.exclude')
            if exists(exclude):
                with open(exclude) as f:
                    # Convert patterns to OS separators
                    patterns = [name.rstrip().replace('/', os.sep) for name in f.readlines()]
                def match(name):
                    for p in patterns:
                        if p in name:
                            if _opts.verbose:
                                log('excluding: ' + name)
                            return True
                    return False

                javafilelist = [name for name in javafilelist if not match(name)]

            batch.sources.extend(javafilelist)

    for key, batch in batches.items():
        if len(batch.sources) == 0:
            continue
        config, checkstyleVersion = key
        checkstyleLibrary = library('CHECKSTYLE_' + checkstyleVersion).get_path(True)
        auditfileName = join(batch.suite.dir, 'checkstyleOutput.txt')
        log('Running Checkstyle [{0}] on {1} using {2}...'.format(checkstyleVersion, ', '.join([p.name for p in batch.projects]), config))
        try:
            for chunk in _chunk_files_for_command_line(batch.sources):
                try:
                    run_java(['-Xmx1g', '-jar', checkstyleLibrary, '-f', 'xml', '-c', config, '-o', auditfileName] + chunk, nonZeroIsFatal=False)
                finally:
                    if exists(auditfileName):
                        errors = []
                        source = [None]
                        def start_element(name, attrs):
                            if name == 'file':
                                source[0] = attrs['name']
                            elif name == 'error':
                                errors.append(u'{0}:{1}: {2}'.format(source[0], attrs['line'], attrs['message']))

                        xp = xml.parsers.expat.ParserCreate()
                        xp.StartElementHandler = start_element
                        with open(auditfileName, 'rb') as fp:
                            xp.ParseFile(fp)
                        if len(errors) != 0:
                            map(log_error, errors)
                            totalErrors = totalErrors + len(errors)
                        else:
                            batch.timestamp.touch()
        finally:
            if exists(auditfileName):
                os.unlink(auditfileName)
    return totalErrors

def help_(args):
    """show detailed help for mx or a given command

With no arguments, print a list of commands and short help for each command.

Given a command name, print help for that command."""
    if len(args) == 0:
        _argParser.print_help()
        return

    name = args[0]
    if name not in _mx_commands.commands():
        hits = [c for c in _mx_commands.commands().keys() if c.startswith(name)]
        if len(hits) == 1:
            name = hits[0]
        elif len(hits) == 0:
            abort('mx: unknown command \'{0}\'\n{1}use "mx help" for more options'.format(name, _format_commands()))
        else:
            abort('mx: command \'{0}\' is ambiguous\n    {1}'.format(name, ' '.join(hits)))

    command = _mx_commands.commands()[name]
    print(command.get_doc())

def _parse_multireleasejar_version(value):
    try:
        mrjVersion = int(value)
        if mrjVersion < 9:
            raise ArgumentTypeError('multi-release jar version ({}) must be greater than 8'.format(value))
        return mrjVersion
    except ValueError:
        raise ArgumentTypeError('multi-release jar version ({}) must be an int value greater than 8'.format(value))

def verifyMultiReleaseProjects(args):
    """verifies properties of multi-release projects"""
    for p in projects():
        if hasattr(p, 'multiReleaseJarVersion') or hasattr(p, 'overlayTarget'):
            compat = p.suite.getMxCompatibility()
            if compat.verify_multirelease_projects():
                # This will abort if there's an error in getting the map
                p.get_overlay_flatten_map()

def flattenMultiReleaseSources(args):
    """print map for flattening multi-release sources

    Prints space separated (versioned_dir, base_dir) pairs where versioned_dir contains versioned sources
    for a multi-release jar and base_dir contains the corresponding non-versioned (or base versioned)
    sources.
    """
    parser = ArgumentParser(prog='mx flattenmultireleasesources')
    parser.add_argument('-c', '--commands', action='store_true', help='format the output as a series of commands to copy '\
                        'the versioned sources to the location of the non-versioned sources')
    parser.add_argument('version', type=int, help='major version of the Java release for which flattened sources will be produced')

    args = parser.parse_args(args)
    versions = {}
    for p in projects():
        if p.isJavaProject() and hasattr(p, 'multiReleaseJarVersion') or hasattr(p, 'overlayTarget'):
            if hasattr(p, 'multiReleaseJarVersion'):
                version = _parse_multireleasejar_version(getattr(p, 'multiReleaseJarVersion'))
            else:
                version = p.javaCompliance.value
            if version <= args.version:
                versions.setdefault(version, []).append(p.get_overlay_flatten_map())
            else:
                # Ignore overlays for versions higher than the one requested
                pass

    # Process versioned overlays in ascending order such that higher versions
    # override lower versions. This corresponds with how versioned classes in
    # multi-release jars are resolved.
    for version, maps in sorted(versions.items()):
        for flatten_map in maps:
            for src_dir, dst_dir in flatten_map.items():
                if not args.commands:
                    print(src_dir, dst_dir)
                else:
                    if not exists(dst_dir):
                        print('mkdir -p {}'.format(dst_dir))
                    print('cp {}{}* {}'.format(src_dir, os.sep, dst_dir))

def projectgraph(args, suite=None):
    """create graph for project structure ("mx projectgraph | dot -Tpdf -oprojects.pdf" or "mx projectgraph --igv")"""

    parser = ArgumentParser(prog='mx projectgraph')
    parser.add_argument('--dist', action='store_true', help='group projects by distribution')
    parser.add_argument('--ignore', action='append', help='dependencies to ignore', default=[])

    args = parser.parse_args(args)

    def should_ignore(name):
        return any((ignored in name for ignored in args.ignore))

    def print_edge(from_dep, to_dep, attributes=None):
        edge_str = ''
        attributes = attributes or {}
        def node_str(_dep):
            _node_str = '"' + _dep.name
            if args.dist and _dep.isDistribution():
                _node_str += ':DUMMY'
            _node_str += '"'
            return _node_str
        edge_str += node_str(from_dep)
        edge_str += '->'
        edge_str += node_str(to_dep)
        if args.dist and from_dep.isDistribution() or to_dep.isDistribution():
            attributes['color'] = 'blue'
            if to_dep.isDistribution():
                attributes['lhead'] = 'cluster_' + to_dep.name
            if from_dep.isDistribution():
                attributes['ltail'] = 'cluster_' + from_dep.name
        if attributes:
            edge_str += ' [' + ', '.join((k + '="' + v + '"' for k, v in attributes.items())) + ']'
        edge_str += ';'
        print(edge_str)

    print('digraph projects {')
    print('rankdir=BT;')
    print('node [shape=rect];')
    print('splines=true;')
    print('ranksep=1;')
    if args.dist:
        print('compound=true;')
        started_dists = set()

        used_libraries = set()
        for p in projects():
            if should_ignore(p.name):
                continue
            for dep in p.deps:
                if dep.isLibrary():
                    used_libraries.add(dep)
        for d in sorted_dists():
            if should_ignore(d.name):
                continue
            for dep in d.excludedLibs:
                used_libraries.add(dep)

        for l in used_libraries:
            if not should_ignore(l.name):
                print('"' + l.name + '";')

        def print_distribution(_d):
            if should_ignore(_d.name):
                return
            if _d in started_dists:
                warn("projectgraph does not support non-strictly nested distributions, result may be inaccurate around " + _d.name)
                return
            started_dists.add(_d)
            print('subgraph "cluster_' + _d.name + '" {')
            print('label="' + _d.name + '";')
            print('color=blue;')
            print('"' + _d.name + ':DUMMY" [shape=point, style=invis];')

            if _d.isDistribution():
                overlapped_deps = set()
                for overlapped in _d.overlapped_distributions():
                    print_distribution(overlapped)
                    overlapped_deps.update(overlapped.archived_deps())
                for p in _d.archived_deps():
                    if p.isProject() and p not in overlapped_deps:
                        if should_ignore(p.name):
                            continue
                        print('"' + p.name + '";')
                        print('"' + _d.name + ':DUMMY"->"' + p.name + '" [style="invis"];')
            print('}')
            for dep in _d.deps:
                if dep.isDistribution():
                    print_edge(_d, dep)
            for dep in _d.excludedLibs:
                print_edge(_d, dep)

        in_overlap = set()
        for d in sorted_dists():
            in_overlap.update(d.overlapped_distributions())
        for d in sorted_dists():
            if d not in started_dists and d not in in_overlap:
                print_distribution(d)

    for p in projects():
        if should_ignore(p.name):
            continue
        for dep in p.deps:
            if should_ignore(dep.name):
                continue
            print_edge(p, dep)
        if p.isJavaProject():
            for apd in p.declaredAnnotationProcessors:
                if should_ignore(apd.name):
                    continue
                print_edge(p, apd, {"style": "dashed"})
    print('}')

def _source_locator_memento(deps, jdk=None):
    slm = XMLDoc()
    slm.open('sourceLookupDirector')
    slm.open('sourceContainers', {'duplicates' : 'false'})

    javaCompliance = None

    sources = []
    for dep in deps:
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                memento = XMLDoc().element('classpathContainer', {'path' : getattr(dep, 'eclipse.container')}).xml(standalone='no')
                slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
                sources.append(getattr(dep, 'eclipse.container') +' [classpathContainer]')
            elif dep.get_source_path(resolve=True):
                memento = XMLDoc().element('archive', {'detectRoot' : 'true', 'path' : dep.get_source_path(resolve=True)}).xml(standalone='no')
                slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.externalArchive'})
                sources.append(dep.get_source_path(resolve=True) + ' [externalArchive]')
        elif dep.isJdkLibrary():
            if jdk is None:
                jdk = get_jdk(tag='default')
            path = dep.get_source_path(jdk)
            if path:
                if os.path.isdir(path):
                    memento = XMLDoc().element('directory', {'nest' : 'false', 'path' : path}).xml(standalone='no')
                    slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.directory'})
                    sources.append(path + ' [directory]')
                else:
                    memento = XMLDoc().element('archive', {'detectRoot' : 'true', 'path' : path}).xml(standalone='no')
                    slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.externalArchive'})
                    sources.append(path + ' [externalArchive]')
        elif dep.isProject():
            if not dep.isJavaProject():
                continue
            memento = XMLDoc().element('javaProject', {'name' : dep.name}).xml(standalone='no')
            slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.javaProject'})
            sources.append(dep.name + ' [javaProject]')
            if javaCompliance is None or dep.javaCompliance > javaCompliance:
                javaCompliance = dep.javaCompliance

    if javaCompliance:
        jdkContainer = 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' +  _to_EclipseJRESystemLibrary(javaCompliance)
        memento = XMLDoc().element('classpathContainer', {'path' : jdkContainer}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
        sources.append(jdkContainer + ' [classpathContainer]')
    else:
        memento = XMLDoc().element('classpathContainer', {'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER'}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
        sources.append('org.eclipse.jdt.launching.JRE_CONTAINER [classpathContainer]')

    slm.close('sourceContainers')
    slm.close('sourceLookupDirector')
    return slm, sources

### ~~~~~~~~~~~~~ IDE / Eclipse / Netbeans / IntelliJ

def make_eclipse_attach(suite, hostname, port, name=None, deps=None, jdk=None):
    """
    Creates an Eclipse launch configuration file for attaching to a Java process.
    """
    if deps is None:
        deps = []
    javaProjects = [p for p in suite.projects if p.isJavaProject()]
    if len(javaProjects) == 0:
        return None, None

    slm, sources = _source_locator_memento(deps, jdk=jdk)
    # Without an entry for the "Project:" field in an attach configuration, Eclipse Neon has problems connecting
    # to a waiting VM and leaves it hanging. Putting any valid project entry in the field seems to solve it.
    firstProjectName = javaProjects[0].name

    launch = XMLDoc()
    launch.open('launchConfiguration', {'type' : 'org.eclipse.jdt.launching.remoteJavaApplication'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_id', 'value' : 'org.eclipse.jdt.launching.sourceLocator.JavaSourceLookupDirector'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_memento', 'value' : '%s'})
    launch.element('booleanAttribute', {'key' : 'org.eclipse.jdt.launching.ALLOW_TERMINATE', 'value' : 'true'})
    launch.open('mapAttribute', {'key' : 'org.eclipse.jdt.launching.CONNECT_MAP'})
    launch.element('mapEntry', {'key' : 'hostname', 'value' : hostname})
    launch.element('mapEntry', {'key' : 'port', 'value' : port})
    launch.close('mapAttribute')
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROJECT_ATTR', 'value' : firstProjectName})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.VM_CONNECTOR_ID', 'value' : 'org.eclipse.jdt.launching.socketAttachConnector'})
    launch.close('launchConfiguration')
    launch = launch.xml(newl='\n', standalone='no') % slm.xml(escape=True, standalone='no')

    if name is None:
        if len(suites()) == 1:
            suitePrefix = ''
        else:
            suitePrefix = suite.name + '-'
        name = suitePrefix + 'attach-' + hostname + '-' + port
    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    ensure_dir_exists(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    sourcesFile = join(eclipseLaunches, name + '.sources')
    update_file(sourcesFile, '\n'.join(sources))
    return update_file(launchFile, launch), launchFile

def make_eclipse_launch(suite, javaArgs, jre, name=None, deps=None):
    """
    Creates an Eclipse launch configuration file for running/debugging a Java command.
    """
    if deps is None:
        deps = []
    mainClass = None
    vmArgs = []
    appArgs = []
    cp = None
    argsCopy = list(reversed(javaArgs))
    while len(argsCopy) != 0:
        a = argsCopy.pop()
        if a == '-jar':
            mainClass = '-jar'
            appArgs = list(reversed(argsCopy))
            break
        if a in _VM_OPTS_SPACE_SEPARATED_ARG:
            assert len(argsCopy) != 0
            cp = argsCopy.pop()
            vmArgs.append(a)
            vmArgs.append(cp)
        elif a.startswith('-'):
            vmArgs.append(a)
        else:
            mainClass = a
            appArgs = list(reversed(argsCopy))
            break

    if mainClass is None:
        log('Cannot create Eclipse launch configuration without main class or jar file: java ' + ' '.join(javaArgs))
        return False

    if name is None:
        if mainClass == '-jar':
            name = basename(appArgs[0])
            if len(appArgs) > 1 and not appArgs[1].startswith('-'):
                name = name + '_' + appArgs[1]
        else:
            name = mainClass
        name = time.strftime('%Y-%m-%d-%H%M%S_' + name)

    if cp is not None:
        for e in cp.split(os.pathsep):
            for s in suites():
                deps += [p for p in s.projects if e == p.output_dir()]
                deps += [l for l in s.libs if e == l.get_path(False)]

    slm, sources = _source_locator_memento(deps)

    launch = XMLDoc()
    launch.open('launchConfiguration', {'type' : 'org.eclipse.jdt.launching.localJavaApplication'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_id', 'value' : 'org.eclipse.jdt.launching.sourceLocator.JavaSourceLookupDirector'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_memento', 'value' : '%s'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.JRE_CONTAINER', 'value' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' + jre})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.MAIN_TYPE', 'value' : mainClass})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROGRAM_ARGUMENTS', 'value' : ' '.join(appArgs)})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROJECT_ATTR', 'value' : ''})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.VM_ARGUMENTS', 'value' : ' '.join(vmArgs)})
    launch.close('launchConfiguration')
    launch = launch.xml(newl='\n', standalone='no') % slm.xml(escape=True, standalone='no')

    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    ensure_dir_exists(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    sourcesFile = join(eclipseLaunches, name + '.sources')
    update_file(sourcesFile, '\n'.join(sources))
    return update_file(launchFile, launch)

def eclipseinit_cli(args):
    """(re)generate Eclipse project configurations and working sets"""
    parser = ArgumentParser(prog='mx eclipseinit')
    parser.add_argument('--no-build', action='store_false', dest='buildProcessorJars', help='Do not build annotation processor jars.')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate PyDev projects for the mx python projects.')
    parser.add_argument('-C', '--log-to-console', action='store_true', dest='logToConsole', help='Send builder output to eclipse console.')
    parser.add_argument('-f', '--force', action='store_true', dest='force', default=False, help='Ignore timestamps when updating files.')
    parser.add_argument('-A', '--absolute-paths', action='store_true', dest='absolutePaths', default=False, help='Use absolute paths in project files.')
    args = parser.parse_args(args)
    eclipseinit(None, args.buildProcessorJars, logToConsole=args.logToConsole, force=args.force, absolutePaths=args.absolutePaths, pythonProjects=args.pythonProjects)
    if _EclipseJRESystemLibraries:
        log('----------------------------------------------')
        executionEnvironments = [n for n in _EclipseJRESystemLibraries if n.startswith('JavaSE-')]
        installedJREs = [n for n in _EclipseJRESystemLibraries if not n.startswith('JavaSE-')]
        if executionEnvironments:
            log('Ensure that these Execution Environments have a Compatible JRE in Eclipse (Preferences -> Java -> Installed JREs -> Execution Environments):')
            for name in executionEnvironments:
                log('  ' + name)
        if installedJREs:
            log('Ensure that there are Installed JREs with these exact names in Eclipse (Preferences -> Java -> Installed JREs):')
            for name in installedJREs:
                log('  ' + name)
            log('You can set the "JRE name" field for a JDK when initially adding it or later with the "Edit..." button.')
            log('See https://help.eclipse.org/photon/topic/org.eclipse.jdt.doc.user/tasks/task-add_new_jre.htm on how to add')
            log('a new JDK to Eclipse. Be sure to select "Standard VM" (even on macOS) for the JRE type.')
        log('----------------------------------------------')

def eclipseinit(args, buildProcessorJars=True, refreshOnly=False, logToConsole=False, doFsckProjects=True, force=False, absolutePaths=False, pythonProjects=False):
    """(re)generate Eclipse project configurations and working sets"""

    for s in suites(True) + [_mx_suite]:
        _eclipseinit_suite(s, buildProcessorJars, refreshOnly, logToConsole, force, absolutePaths, pythonProjects)

    wsroot = generate_eclipse_workingsets()

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

    return wsroot

def _check_ide_timestamp(suite, configZip, ide, settingsFile=None):
    """
    Returns True if and only if suite.py for `suite`, all `configZip` related resources in
    `suite` and mx itself are older than `configZip`.
    """
    suitePyFiles = [join(suite.mxDir, e) for e in os.listdir(suite.mxDir) if e == 'suite.py']
    if configZip.isOlderThan(suitePyFiles):
        return False
    # Assume that any mx change might imply changes to the generated IDE files
    if configZip.isOlderThan(__file__):
        return False

    if settingsFile and configZip.isOlderThan(settingsFile):
        return False

    if ide == 'eclipse':
        for proj in [p for p in suite.projects]:
            if not proj.eclipse_config_up_to_date(configZip):
                return False

    if ide == 'netbeans':
        for proj in [p for p in suite.projects]:
            if not proj.netbeans_config_up_to_date(configZip):
                return False

    return True

EclipseLinkedResource = namedtuple('LinkedResource', ['name', 'type', 'location'])
def _eclipse_linked_resource(name, tp, location):
    return EclipseLinkedResource(name, tp, location)

def get_eclipse_project_rel_locationURI(path, eclipseProjectDir):
    """
    Gets the URI for a resource relative to an Eclipse project directory (i.e.,
    the directory containing the `.project` file for the project). The URI
    returned is based on the builtin PROJECT_LOC Eclipse variable.
    See http://stackoverflow.com/a/7585095
    """
    relpath = os.path.relpath(path, eclipseProjectDir)
    names = relpath.split(os.sep)
    parents = len([n for n in names if n == '..'])
    sep = '/' # Yes, even on Windows...
    if parents:
        projectLoc = 'PARENT-{}-PROJECT_LOC'.format(parents)
    else:
        projectLoc = 'PROJECT_LOC'
    return sep.join([projectLoc] + [n for n in names if n != '..'])

def _get_eclipse_output_path(p, linkedResources=None):
    """
    Gets the Eclipse path attribute value for the output of project `p`.
    """
    outputDirRel = p.output_dir(relative=True)
    if outputDirRel.startswith('..'):
        outputDirName = basename(outputDirRel)
        if linkedResources is not None:
            linkedResources.append(_eclipse_linked_resource(outputDirName, '2', p.output_dir()))
        return outputDirName
    else:
        return outputDirRel

#: Highest Execution Environment defined by most recent Eclipse release.
#: https://wiki.eclipse.org/Execution_Environments
_max_Eclipse_JavaExecutionEnvironment = 10 # pylint: disable=invalid-name

_EclipseJRESystemLibraries = set()

def _to_EclipseJRESystemLibrary(compliance):
    """
    Converts a Java compliance value to a JRE System Library that
    can be put on a project's Build Path.
    """
    if not isinstance(compliance, JavaCompliance):
        compliance = JavaCompliance(compliance)

    if compliance.value > _max_Eclipse_JavaExecutionEnvironment:
        res = 'jdk-' + str(compliance)
    else:
        res = 'JavaSE-' + str(compliance)
    _EclipseJRESystemLibraries.add(res)
    return res

def _eclipseinit_project(p, files=None, libFiles=None, absolutePaths=False):
    ensure_dir_exists(p.dir)

    linkedResources = []

    out = XMLDoc()
    out.open('classpath')

    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        ensure_dir_exists(srcDir)
        out.element('classpathentry', {'kind' : 'src', 'path' : src})

    processors = p.annotation_processors()
    if processors:
        genDir = p.source_gen_dir()
        ensure_dir_exists(genDir)
        if not genDir.startswith(p.dir):
            genDirName = basename(genDir)
            out.open('classpathentry', {'kind' : 'src', 'path' : genDirName})
            linkedResources.append(_eclipse_linked_resource(genDirName, '2', genDir))
        else:
            out.open('classpathentry', {'kind' : 'src', 'path' : p.source_gen_dir(relative=True)})

        if [ap for ap in p.declaredAnnotationProcessors if ap.isLibrary()]:
            # ignore warnings produced by third-party annotation processors
            out.open('attributes')
            out.element('attribute', {'name' : 'ignore_optional_problems', 'value' : 'true'})
            out.close('attributes')
        out.close('classpathentry')
        if files:
            files.append(genDir)

    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.pde.core.requiredPlugins'})

    containerDeps = set()
    libraryDeps = set()
    jdkLibraryDeps = set()
    projectDeps = set()
    distributionDeps = set()

    def processDep(dep, edge):
        if dep is p:
            return
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                container = getattr(dep, 'eclipse.container')
                containerDeps.add(container)
                dep.walk_deps(visit=lambda dep2, edge2: libraryDeps.discard(dep2))
            else:
                libraryDeps.add(dep)
        elif dep.isJavaProject() or dep.isNativeProject():
            projectDeps.add(dep)
        elif dep.isMavenProject():
            libraryDeps.add(dep)
        elif dep.isJdkLibrary():
            jdkLibraryDeps.add(dep)
        elif dep.isJARDistribution() and isinstance(dep.suite, BinarySuite):
            distributionDeps.add(dep)
        elif dep.isJreLibrary() or dep.isDistribution():
            pass
        elif dep.isProject():
            logv('ignoring project ' + dep.name + ' for eclipseinit')
        else:
            abort('unexpected dependency: ' + str(dep))
    p.walk_deps(visit=processDep)

    for dep in sorted(containerDeps):
        out.element('classpathentry', {'exported' : 'true', 'kind' : 'con', 'path' : dep})

    for dep in sorted(distributionDeps):
        out.element('classpathentry', {'exported' : 'true', 'kind' : 'lib', 'path' : dep.path, 'sourcepath' : dep.sourcesPath})

    for dep in sorted(libraryDeps):
        path = dep.get_path(resolve=True)

        # Relative paths for "lib" class path entries have various semantics depending on the Eclipse
        # version being used (e.g. see https://bugs.eclipse.org/bugs/show_bug.cgi?id=274737) so it's
        # safest to simply use absolute paths.

        # It's important to use dep.suite as the location for when one suite references
        # a library in another suite.
        path = _make_absolute(path, dep.suite.dir)

        attributes = {'exported' : 'true', 'kind' : 'lib', 'path' : path}

        sourcePath = dep.get_source_path(resolve=True)
        if sourcePath is not None:
            attributes['sourcepath'] = sourcePath
        out.element('classpathentry', attributes)
        if libFiles:
            libFiles.append(path)

    jdk = get_jdk(p.javaCompliance)
    for dep in sorted(jdkLibraryDeps):
        path = dep.classpath_repr(jdk, resolve=True)
        if path:
            attributes = {'exported' : 'true', 'kind' : 'lib', 'path' : path}
            sourcePath = dep.get_source_path(jdk)
            if sourcePath is not None:
                attributes['sourcepath'] = sourcePath
            out.element('classpathentry', attributes)
            if libFiles:
                libFiles.append(path)

    # When targeting JDK 8 or earlier, dependencies need to precede the JDK on the Eclipse build path.
    # There may be classes in dependencies that are also in the JDK. We want to compile against the
    # former. This is the same -Xbootclasspath:/p trick done in JavacLikeCompiler.prepare.
    putJREFirstOnBuildPath = p.javaCompliance.value >= 9

    sortedDeps = sorted(projectDeps)
    allProjectPackages = set()
    for dep in sortedDeps:
        if not dep.isNativeProject():
            allProjectPackages.update(dep.defined_java_packages())
            if not putJREFirstOnBuildPath:
                out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    # Every Java program depends on a JRE
    jreSystemLibrary = _to_EclipseJRESystemLibrary(jdk.javaCompliance)
    out.open('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' + jreSystemLibrary})
    if jdk.javaCompliance >= '9':
        out.open('attributes')
        out.element('attribute', {'name' : 'module', 'value' : 'true'})
        moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
        if len(moduleDeps) != 0:
            # Ignore modules (such as jdk.internal.vm.compiler) that define packages
            # that are also defined by project deps as the latter will have the most
            # recent API.
            exports = sorted([(module, pkgs) for module, pkgs in moduleDeps.items() if allProjectPackages.isdisjoint(pkgs)])
            if exports:
                addExportsValue = []
                exported_modules = []
                for module, pkgs in exports:
                    addExportsValue.extend([module + '/' + pkg + '=ALL-UNNAMED' for pkg in pkgs])
                    exported_modules.append(module)
                out.element('attribute', {'name' : 'add-exports', 'value' : ':'.join(addExportsValue)})
                roots = jdk.get_root_modules()
                observable_modules = jdk.get_modules()
                default_module_graph = get_transitive_closure(roots, observable_modules)
                module_graph = get_transitive_closure(roots + exported_modules, observable_modules)
                if default_module_graph != module_graph:
                    # https://github.com/eclipse/eclipse.jdt.core/blob/00dd337bcfe08d8b2d60529b0f7874b88e621c06/org.eclipse.jdt.core/model/org/eclipse/jdt/internal/core/JavaProject.java#L704-L715
                    out.element('attribute', {'name' : 'limit-modules', 'value' : ','.join([m.name for m in module_graph])})
        out.close('attributes')
    out.close('classpathentry')

    if putJREFirstOnBuildPath:
        for dep in sortedDeps:
            if not dep.isNativeProject():
                out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    out.element('classpathentry', {'kind' : 'output', 'path' : _get_eclipse_output_path(p, linkedResources)})

    out.close('classpath')
    classpathFile = join(p.dir, '.classpath')
    update_file(classpathFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(classpathFile)

    csConfig, _, checkstyleProj = p.get_checkstyle_config()
    if csConfig:
        out = XMLDoc()

        dotCheckstyle = join(p.dir, ".checkstyle")
        checkstyleConfigPath = '/' + checkstyleProj.name + '/.checkstyle_checks.xml'
        out.open('fileset-config', {'file-format-version' : '1.2.0', 'simple-config' : 'false'})
        out.open('local-check-config', {'name' : 'Checks', 'location' : checkstyleConfigPath, 'type' : 'project', 'description' : ''})
        out.element('additional-data', {'name' : 'protect-config-file', 'value' : 'false'})
        out.close('local-check-config')
        out.open('fileset', {'name' : 'all', 'enabled' : 'true', 'check-config-name' : 'Checks', 'local' : 'true'})
        out.element('file-match-pattern', {'match-pattern' : r'.*\.java$', 'include-pattern' : 'true'})
        out.element('file-match-pattern', {'match-pattern' : p.source_gen_dir_name() + os.sep + '.*', 'include-pattern' : 'false'})
        out.element('file-match-pattern', {'match-pattern' : '/package-info.java$', 'include-pattern' : 'false'})
        out.close('fileset')

        exclude = join(p.dir, '.checkstyle.exclude')
        if False  and exists(exclude):
            out.open('filter', {'name' : 'FilesFromPackage', 'enabled' : 'true'})
            with open(exclude) as f:
                for line in f:
                    if not line.startswith('#'):
                        line = line.strip()
                    out.element('filter-data', {'value' : line})
            out.close('filter')

        out.close('fileset-config')
        update_file(dotCheckstyle, out.xml(indent='  ', newl='\n'))
        if files:
            files.append(dotCheckstyle)
    else:
        # clean up existing .checkstyle file
        dotCheckstyle = join(p.dir, ".checkstyle")
        if exists(dotCheckstyle):
            os.unlink(dotCheckstyle)

    out = XMLDoc()
    out.open('projectDescription')
    out.element('name', data=p.name)
    out.element('comment', data='')
    out.open('projects')
    for dep in sorted(projectDeps):
        if not dep.isNativeProject():
            out.element('project', data=dep.name)
    out.close('projects')
    out.open('buildSpec')
    out.open('buildCommand')
    out.element('name', data='org.eclipse.jdt.core.javabuilder')
    out.element('arguments', data='')
    out.close('buildCommand')
    if csConfig:
        out.open('buildCommand')
        out.element('name', data='net.sf.eclipsecs.core.CheckstyleBuilder')
        out.element('arguments', data='')
        out.close('buildCommand')
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        for buildCommand in ['org.eclipse.pde.ManifestBuilder', 'org.eclipse.pde.SchemaBuilder']:
            out.open('buildCommand')
            out.element('name', data=buildCommand)
            out.element('arguments', data='')
            out.close('buildCommand')

    out.close('buildSpec')
    out.open('natures')
    out.element('nature', data='org.eclipse.jdt.core.javanature')
    if csConfig:
        out.element('nature', data='net.sf.eclipsecs.core.CheckstyleNature')
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('nature', data='org.eclipse.pde.PluginNature')
    out.close('natures')
    if linkedResources:
        out.open('linkedResources')
        for lr in linkedResources:
            out.open('link')
            out.element('name', data=lr.name)
            out.element('type', data=lr.type)
            out.element('locationURI', data=get_eclipse_project_rel_locationURI(lr.location, p.dir) if not absolutePaths else lr.location)
            out.close('link')
        out.close('linkedResources')
    out.close('projectDescription')
    projectFile = join(p.dir, '.project')
    update_file(projectFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(projectFile)

    # copy a possibly modified file to the project's .settings directory
    _copy_eclipse_settings(p, files)

    if processors:
        out = XMLDoc()
        out.open('factorypath')
        out.element('factorypathentry', {'kind' : 'PLUGIN', 'id' : 'org.eclipse.jst.ws.annotations.core', 'enabled' : 'true', 'runInBatchMode' : 'false'})
        processorsPath = classpath_entries(names=processors)
        for e in processorsPath:
            if e.isDistribution() and not isinstance(e.suite, BinarySuite):
                out.element('factorypathentry', {'kind' : 'WKSPJAR', 'id' : '/{0}/{1}'.format(e.name, basename(e.path)), 'enabled' : 'true', 'runInBatchMode' : 'false'})
            elif e.isJdkLibrary() or e.isJreLibrary():
                path = e.classpath_repr(jdk, resolve=True)
                if path:
                    out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : path, 'enabled' : 'true', 'runInBatchMode' : 'false'})
            else:
                out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : e.classpath_repr(resolve=True), 'enabled' : 'true', 'runInBatchMode' : 'false'})

        if p.javaCompliance >= '9':
            concealedAPDeps = {}
            for dep in classpath_entries(names=processors, preferProjects=True):
                if dep.isJavaProject():
                    concealed = dep.get_concealed_imported_packages(jdk)
                    if concealed:
                        for module, pkgs in concealed.items():
                            concealedAPDeps.setdefault(module, []).extend(pkgs)
            if concealedAPDeps:
                exports = []
                for module, pkgs in concealedAPDeps.items():
                    for pkg in pkgs:
                        exports.append('--add-exports=' + module + '/' + pkg + '=ALL-UNNAMED')
                warn('Annotation processor(s) for ' + p.name +' uses non-exported module packages, requiring ' +
                     'the following to be added to eclipse.ini:\n' +
                     '\n'.join(exports))

        out.close('factorypath')
        update_file(join(p.dir, '.factorypath'), out.xml(indent='\t', newl='\n'))
        if files:
            files.append(join(p.dir, '.factorypath'))

_ide_envvars = {
    'MX_ALT_OUTPUT_ROOT' : None,
    # On the mac, applications are launched with a different path than command
    # line tools, so capture the current PATH.  In general this ensures that
    # the eclipse builders see the same path as a working command line build.
    'PATH' : None,
}

def add_ide_envvar(name, value=None):
    """
    Adds a given name to the set of environment variables that will
    be captured in generated IDE configurations. If `value` is not
    None, then it will be the captured value. Otherwise the result of
    get_env(name) is not None as capturing time, it will be used.
    Otherwise no value is captured.
    """
    _ide_envvars[name] = value

def _get_ide_envvars():
    """
    Gets a dict of environment variables that must be captured in generated IDE configurations.
    """
    result = {
        'JAVA_HOME' : get_env('JAVA_HOME') or get_jdk().home,
        'EXTRA_JAVA_HOMES' : get_env('EXTRA_JAVA_HOMES'),
    }
    for name, value in _ide_envvars.items():
        if value is None:
            value = get_env(name)
        if value is not None:
            result[name] = value
    return result

def _capture_eclipse_settings(logToConsole, absolutePaths):
    # Capture interesting settings which drive the output of the projects.
    # Changes to these values should cause regeneration of the project files.
    settings = 'logToConsole=%s\n' % logToConsole
    settings = settings + 'absolutePaths=%s\n' % absolutePaths
    for name, value in _get_ide_envvars().items():
        settings = settings + '%s=%s\n' % (name, value)
    return settings

def _eclipseinit_suite(s, buildProcessorJars=True, refreshOnly=False, logToConsole=False, force=False, absolutePaths=False, pythonProjects=False):
    # a binary suite archive is immutable and no project sources, only the -sources.jar
    # TODO We may need the project (for source debugging) but it needs different treatment
    if isinstance(s, BinarySuite):
        return

    mxOutputDir = ensure_dir_exists(s.get_mx_output_dir())
    configZip = TimeStampFile(join(mxOutputDir, 'eclipse-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    settingsFile = join(mxOutputDir, 'eclipse-project-settings')
    update_file(settingsFile, _capture_eclipse_settings(logToConsole, absolutePaths))
    if not force and _check_ide_timestamp(s, configZip, 'eclipse', settingsFile):
        logv('[Eclipse configurations for {} are up to date - skipping]'.format(s.name))
        return

    files = []
    libFiles = []
    if buildProcessorJars:
        files += _processorjars_suite(s)

    for p in s.projects:
        code = _function_code(p._eclipseinit)
        if 'absolutePaths' in code.co_varnames[:code.co_argcount]:
            p._eclipseinit(files, libFiles, absolutePaths=absolutePaths)
        else:
            # Support legacy signature
            p._eclipseinit(files, libFiles)

    jdk = get_jdk(tag='default')
    _, launchFile = make_eclipse_attach(s, 'localhost', '8000', deps=dependencies(), jdk=jdk)
    if launchFile:
        files.append(launchFile)

    # Create an Eclipse project for each distribution that will create/update the archive
    # for the distribution whenever any (transitively) dependent project of the
    # distribution is updated.
    for dist in s.dists:
        if not dist.isJARDistribution():
            continue
        projectDir = dist.get_ide_project_dir()
        if not projectDir:
            continue
        ensure_dir_exists(projectDir)
        relevantResources = []
        relevantResourceDeps = set(dist.archived_deps())
        for d in sorted(relevantResourceDeps):
            # Eclipse does not seem to trigger a build for a distribution if the references
            # to the constituent projects are of type IRESOURCE_PROJECT.
            if d.isJavaProject():
                for srcDir in d.srcDirs:
                    relevantResources.append(RelevantResource('/' + d.name + '/' + srcDir, IRESOURCE_FOLDER))
                relevantResources.append(RelevantResource('/' +d.name + '/' + _get_eclipse_output_path(d), IRESOURCE_FOLDER))

        out = XMLDoc()
        out.open('projectDescription')
        out.element('name', data=dist.name)
        out.element('comment', data='Updates ' + dist.path + ' if a project dependency of ' + dist.name + ' is updated')
        out.open('projects')
        for d in sorted(relevantResourceDeps):
            out.element('project', data=d.name)
        out.close('projects')
        out.open('buildSpec')
        dist.dir = projectDir
        builders = _genEclipseBuilder(out, dist, 'Create' + dist.name + 'Dist', '-v archive @' + dist.name,
                                      relevantResources=relevantResources,
                                      logToFile=True, refresh=True, isAsync=False,
                                      logToConsole=logToConsole, appendToLogFile=False,
                                      refreshFile='/{0}/{1}'.format(dist.name, basename(dist.path)))
        files = files + builders

        out.close('buildSpec')
        out.open('natures')
        out.element('nature', data='org.eclipse.jdt.core.javanature')
        out.close('natures')
        out.open('linkedResources')
        out.open('link')
        out.element('name', data=basename(dist.path))
        out.element('type', data=str(IRESOURCE_FILE))
        out.element('location', data=get_eclipse_project_rel_locationURI(dist.path, projectDir) if not absolutePaths else dist.path)
        out.close('link')
        out.close('linkedResources')
        out.close('projectDescription')
        projectFile = join(projectDir, '.project')
        update_file(projectFile, out.xml(indent='\t', newl='\n'))
        files.append(projectFile)

    if pythonProjects:
        projectXml = XMLDoc()
        projectXml.open('projectDescription')
        projectXml.element('name', data=s.name if s is _mx_suite else 'mx.' + s.name)
        projectXml.element('comment')
        projectXml.open('projects')
        if s is not _mx_suite:
            projectXml.element('project', data=_mx_suite.name)
        processed_suites = set([s.name])
        def _mx_projects_suite(visited_suite, suite_import):
            if suite_import.name in processed_suites:
                return
            processed_suites.add(suite_import.name)
            dep_suite = suite(suite_import.name)
            projectXml.element('project', data='mx.' + suite_import.name)
            dep_suite.visit_imports(_mx_projects_suite)
        s.visit_imports(_mx_projects_suite)
        projectXml.close('projects')
        projectXml.open('buildSpec')
        projectXml.open('buildCommand')
        projectXml.element('name', data='org.python.pydev.PyDevBuilder')
        projectXml.element('arguments')
        projectXml.close('buildCommand')
        projectXml.close('buildSpec')
        projectXml.open('natures')
        projectXml.element('nature', data='org.python.pydev.pythonNature')
        projectXml.close('natures')
        projectXml.close('projectDescription')
        projectFile = join(s.dir if s is _mx_suite else s.mxDir, '.project')
        update_file(projectFile, projectXml.xml(indent='  ', newl='\n'))
        files.append(projectFile)

        pydevProjectXml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?eclipse-pydev version="1.0"?>
<pydev_project>
<pydev_property name="org.python.pydev.PYTHON_PROJECT_INTERPRETER">Default</pydev_property>
<pydev_property name="org.python.pydev.PYTHON_PROJECT_VERSION">python 2.7</pydev_property>
<pydev_pathproperty name="org.python.pydev.PROJECT_SOURCE_PATH">
<path>/{}</path>
</pydev_pathproperty>
</pydev_project>
""".format(s.name if s is _mx_suite else 'mx.' + s.name)
        pydevProjectFile = join(s.dir if s is _mx_suite else s.mxDir, '.pydevproject')
        update_file(pydevProjectFile, pydevProjectXml)
        files.append(pydevProjectFile)

    _zip_files(files + [settingsFile], s.dir, configZip.path)
    _zip_files(libFiles, s.dir, configLibsZip)

def _zip_files(files, baseDir, zipPath):
    with SafeFileCreation(zipPath) as sfc:
        zf = zipfile.ZipFile(sfc.tmpPath, 'w')
        for f in sorted(set(files)):
            relpath = os.path.relpath(f, baseDir)
            arcname = relpath.replace(os.sep, '/')
            zf.write(f, arcname)
        zf.close()

RelevantResource = namedtuple('RelevantResource', ['path', 'type'])

# http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.core/resources/3.9.1/org/eclipse/core/resources/IResource.java#76
IRESOURCE_FILE = 1
IRESOURCE_FOLDER = 2

def _genEclipseBuilder(dotProjectDoc, p, name, mxCommand, refresh=True, refreshFile=None, relevantResources=None, isAsync=False, logToConsole=False, logToFile=False, appendToLogFile=True, xmlIndent='\t', xmlStandalone=None):
    externalToolDir = join(p.dir, '.externalToolBuilders')
    launchOut = XMLDoc()
    consoleOn = 'true' if logToConsole else 'false'
    launchOut.open('launchConfiguration', {'type' : 'org.eclipse.ui.externaltools.ProgramBuilderLaunchConfigurationType'})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.capture_output', 'value': consoleOn})
    launchOut.open('mapAttribute', {'key' : 'org.eclipse.debug.core.environmentVariables'})
    for key, value in _get_ide_envvars().items():
        launchOut.element('mapEntry', {'key' : key, 'value' : value})
    launchOut.close('mapAttribute')

    if refresh:
        if refreshFile is None:
            refreshScope = '${project}'
        else:
            refreshScope = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources><item path="' + refreshFile + '" type="' + str(IRESOURCE_FILE) + '"/></resources>}'

        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_RECURSIVE', 'value':  'false'})
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_SCOPE', 'value':  refreshScope})

    if relevantResources:
        # http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.debug/core/3.9.1/org/eclipse/debug/core/RefreshUtil.java#169
        resources = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources>'
        for relevantResource in relevantResources:
            resources += '<item path="' + relevantResource.path + '" type="' + str(relevantResource.type) + '"/>'
        resources += '</resources>}'
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_BUILD_SCOPE', 'value': resources})

    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CONSOLE_OUTPUT_ON', 'value': consoleOn})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_LAUNCH_IN_BACKGROUND', 'value': 'true' if isAsync else 'false'})
    if logToFile:
        logFile = join(externalToolDir, name + '.log')
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CAPTURE_IN_FILE', 'value': logFile})
        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_APPEND_TO_FILE', 'value': 'true' if appendToLogFile else 'false'})

    # expect to find the OS command to invoke mx in the same directory
    baseDir = dirname(os.path.abspath(__file__))

    cmd = 'mx'
    if is_windows():
        cmd = 'mx.cmd'
    cmdPath = join(baseDir, cmd)
    if not os.path.exists(cmdPath):
        # backwards compatibility for when the commands lived in parent of mxtool
        if cmd == 'mx':
            cmd = 'mx.sh'
        cmdPath = join(dirname(baseDir), cmd)
        if not os.path.exists(cmdPath):
            abort('cannot locate ' + cmd)

    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_LOCATION', 'value':  cmdPath})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_RUN_BUILD_KINDS', 'value': 'auto,full,incremental'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TOOL_ARGUMENTS', 'value': mxCommand})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TRIGGERS_CONFIGURED', 'value': 'true'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_WORKING_DIRECTORY', 'value': p.suite.dir})


    launchOut.close('launchConfiguration')

    ensure_dir_exists(externalToolDir)
    launchFile = join(externalToolDir, name + '.launch')
    update_file(launchFile, launchOut.xml(indent=xmlIndent, standalone=xmlStandalone, newl='\n'))

    dotProjectDoc.open('buildCommand')
    dotProjectDoc.element('name', data='org.eclipse.ui.externaltools.ExternalToolBuilder')
    dotProjectDoc.element('triggers', data='auto,full,incremental,')
    dotProjectDoc.open('arguments')
    dotProjectDoc.open('dictionary')
    dotProjectDoc.element('key', data='LaunchConfigHandle')
    dotProjectDoc.element('value', data='<project>/.externalToolBuilders/' + name + '.launch')
    dotProjectDoc.close('dictionary')
    dotProjectDoc.open('dictionary')
    dotProjectDoc.element('key', data='incclean')
    dotProjectDoc.element('value', data='true')
    dotProjectDoc.close('dictionary')
    dotProjectDoc.close('arguments')
    dotProjectDoc.close('buildCommand')
    return [launchFile]

def generate_eclipse_workingsets():
    """
    Populate the workspace's working set configuration with working sets generated from project data for the primary suite
    If the workspace already contains working set definitions, the existing ones will be retained and extended.
    In case mx/env does not contain a WORKSPACE definition pointing to the workspace root directory, a parent search from the primary suite directory is performed.
    If no workspace root directory can be identified, the primary suite directory is used and the user has to place the workingsets.xml file by hand.
    """

    # identify the location where to look for workingsets.xml
    wsfilename = 'workingsets.xml'
    wsloc = '.metadata/.plugins/org.eclipse.ui.workbench'
    if 'WORKSPACE' in os.environ:
        expected_wsroot = os.environ['WORKSPACE']
    else:
        expected_wsroot = primary_suite().dir

    wsroot = _find_eclipse_wsroot(expected_wsroot)
    if wsroot is None:
        # failed to find it
        wsroot = expected_wsroot

    wsdir = join(wsroot, wsloc)
    if not exists(wsdir):
        wsdir = wsroot
        logv('Could not find Eclipse metadata directory. Please place ' + wsfilename + ' in ' + wsloc + ' manually.')
    wspath = join(wsdir, wsfilename)

    def _add_to_working_set(key, value):
        if key not in workingSets:
            workingSets[key] = [value]
        else:
            workingSets[key].append(value)

    # gather working set info from project data
    workingSets = dict()
    for p in projects():
        if p.workingSets is None:
            continue
        for w in p.workingSets.split(","):
            _add_to_working_set(w, p.name)

    # the mx metdata directories are included in the appropriate working sets
    _add_to_working_set('MX', 'mxtool')
    for suite in suites(True):
        _add_to_working_set('MX', basename(suite.mxDir))

    if exists(wspath):
        wsdoc = _copy_workingset_xml(wspath, workingSets)
    else:
        wsdoc = _make_workingset_xml(workingSets)

    update_file(wspath, wsdoc.xml(newl='\n'))
    return wsroot

def _find_eclipse_wsroot(wsdir):
    md = join(wsdir, '.metadata')
    if exists(md):
        return wsdir
    split = os.path.split(wsdir)
    if split[0] == wsdir:  # root directory
        return None
    else:
        return _find_eclipse_wsroot(split[0])

def _make_workingset_xml(workingSets):
    wsdoc = XMLDoc()
    wsdoc.open('workingSetManager')

    for w in sorted(workingSets.keys()):
        _workingset_open(wsdoc, w)
        for p in workingSets[w]:
            _workingset_element(wsdoc, p)
        wsdoc.close('workingSet')

    wsdoc.close('workingSetManager')
    return wsdoc

def _copy_workingset_xml(wspath, workingSets):
    target = XMLDoc()
    target.open('workingSetManager')

    parser = xml.parsers.expat.ParserCreate()

    class ParserState(object):
        def __init__(self):
            self.current_ws_name = 'none yet'
            self.current_ws = None
            self.seen_ws = list()
            self.seen_projects = list()
            self.aggregate_ws = False
            self.nested_ws = False

    ps = ParserState()

    # parsing logic
    def _ws_start(name, attributes):
        if name == 'workingSet':
            if 'name' in attributes:
                ps.current_ws_name = attributes['name']
                if 'aggregate' in attributes and attributes['aggregate'] == 'true':
                    ps.aggregate_ws = True
                    ps.current_ws = None
                elif ps.current_ws_name in workingSets:
                    ps.current_ws = workingSets[ps.current_ws_name]
                    ps.seen_ws.append(ps.current_ws_name)
                    ps.seen_projects = list()
                else:
                    ps.current_ws = None
            target.open(name, attributes)
            parser.StartElementHandler = _ws_item

    def _ws_end(name):
        closeAndResetHandler = False
        if name == 'workingSet':
            if ps.aggregate_ws:
                if ps.nested_ws:
                    ps.nested_ws = False
                else:
                    ps.aggregate_ws = False
                    closeAndResetHandler = True
            else:
                if not ps.current_ws is None:
                    for p in ps.current_ws:
                        if not p in ps.seen_projects:
                            _workingset_element(target, p)
                closeAndResetHandler = True
            if closeAndResetHandler:
                target.close('workingSet')
                parser.StartElementHandler = _ws_start
        elif name == 'workingSetManager':
            # process all working sets that are new to the file
            for w in sorted(workingSets.keys()):
                if not w in ps.seen_ws:
                    _workingset_open(target, w)
                    for p in workingSets[w]:
                        _workingset_element(target, p)
                    target.close('workingSet')

    def _ws_item(name, attributes):
        if name == 'item':
            if ps.current_ws is None:
                target.element(name, attributes)
            elif not 'elementID' in attributes and 'factoryID' in attributes and 'path' in attributes and 'type' in attributes:
                target.element(name, attributes)
                p_name = attributes['path'][1:]  # strip off the leading '/'
                ps.seen_projects.append(p_name)
            else:
                p_name = attributes['elementID'][1:]  # strip off the leading '='
                _workingset_element(target, p_name)
                ps.seen_projects.append(p_name)
        elif name == 'workingSet':
            ps.nested_ws = True
            target.element(name, attributes)

    # process document
    parser.StartElementHandler = _ws_start
    parser.EndElementHandler = _ws_end
    with open(wspath, 'rb') as wsfile:
        parser.ParseFile(wsfile)

    target.close('workingSetManager')
    return target

def _workingset_open(wsdoc, ws):
    wsdoc.open('workingSet', {'editPageID': 'org.eclipse.jdt.ui.JavaWorkingSetPage', 'factoryID': 'org.eclipse.ui.internal.WorkingSetFactory', 'id': 'wsid_' + ws, 'label': ws, 'name': ws})

def _workingset_element(wsdoc, p):
    wsdoc.element('item', {'elementID': '=' + p, 'factoryID': 'org.eclipse.jdt.ui.PersistableJavaElementFactory'})

def netbeansinit(args, refreshOnly=False, buildProcessorJars=True, doFsckProjects=True):
    """(re)generate NetBeans project configurations"""

    for suite in suites(True) + [_mx_suite]:
        _netbeansinit_suite(args, suite, refreshOnly, buildProcessorJars)

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

def _netbeansinit_project(p, jdks=None, files=None, libFiles=None, dists=None):
    dists = [] if dists is None else dists
    ensure_dir_exists(join(p.dir, 'nbproject'))

    jdk = get_jdk(p.javaCompliance)
    assert jdk

    if jdks:
        jdks.add(jdk)

    execDir = primary_suite().dir

    out = XMLDoc()
    out.open('project', {'name' : p.name, 'default' : 'default', 'basedir' : '.'})
    out.element('description', data='Builds, tests, and runs the project ' + p.name + '.')
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'build.impl.exists'})
    out.element('import', {'file' : 'nbproject/build-impl.xml', 'optional' : 'true'})
    out.element('extension-point', {'name' : '-mx-init'})
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'mx.init.targets', 'value' : 'init'})
    out.element('property', {'name' : 'mx.init.targets', 'value' : ''})
    out.element('bindtargets', {'extensionPoint' : '-mx-init', 'targets' : '${mx.init.targets}'})

    out.open('target', {'name' : '-post-init'})
    out.open('pathconvert', {'property' : 'comma.javac.classpath', 'pathsep' : ','})
    out.element('path', {'path' : '${javac.classpath}'})
    out.close('pathconvert')

    out.open('restrict', {'id' : 'missing.javac.classpath'})
    out.element('filelist', {'dir' : '${basedir}', 'files' : '${comma.javac.classpath}'})
    out.open('not')
    out.element('exists')
    out.close('not')
    out.close('restrict')

    out.element('property', {'name' : 'missing.javac.classpath', 'refid' : 'missing.javac.classpath'})

    out.open('condition', {'property' : 'no.dependencies', 'value' : 'true'})
    out.element('equals', {'arg1' : '${missing.javac.classpath}', 'arg2' : ''})
    out.close('condition')

    out.element('property', {'name' : 'no.dependencies', 'value' : 'false'})

    out.open('condition', {'property' : 'no.deps'})
    out.element('equals', {'arg1' : '${no.dependencies}', 'arg2' : 'true'})
    out.close('condition')

    out.close('target')
    out.open('target', {'name' : 'clean'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'clean'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'compile'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'build'})
    dependsOn = p.name
    for d in dists:
        dependsOn = dependsOn + ',' + d.name
    out.element('arg', {'value' : '--only'})
    out.element('arg', {'value' : dependsOn})
    out.element('arg', {'value' : '--force-javac'})
    out.element('arg', {'value' : '--no-native'})
    out.element('arg', {'value' : '--no-daemon'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'package', 'if' : 'build.impl.exists'})
    out.element('antcall', {'target': '-package', 'inheritall': 'true', 'inheritrefs': 'true'})
    out.close('target')
    out.open('target', {'name' : '-package', 'depends' : '-mx-init'})
    out.element('loadfile', {'srcFile' : join(p.suite.get_output_root(), 'netbeans.log'), 'property' : 'netbeans.log', 'failonerror' : 'false'})
    out.element('echo', {'message' : '...truncated...${line.separator}', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.element('echo', {'message' : '${netbeans.log}'})
    for d in dists:
        if d.isDistribution():
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name})
            out.element('echo', {'message' : d.name + ' set to now${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.open('copy', {'todir' : '${build.classes.dir}', 'overwrite' : 'true'})
    out.element('resources', {'refid' : 'changed.files'})
    out.close('copy')
    if len(p.annotation_processors()) > 0:
        out.open('copy', {'todir' : '${src.ap-source-output.dir}'})
        out.open('fileset', {'dir': '${cos.src.dir.internal}/../sources/'})
        out.element('include', {'name': '**/*.java'})
        out.close('fileset')
        out.close('copy')
    out.open('exec', {'executable' : '${ant.home}/bin/ant', 'spawn' : 'true'})
    out.element('arg', {'value' : '-f'})
    out.element('arg', {'value' : '${ant.file}'})
    out.element('arg', {'value' : 'packagelater'})
    out.close('exec')
    out.close('target')
    for d in dists:
        if d.isDistribution():
            out.open('target', {'name' : 'checkpackage-' + d.name})
            out.open('tstamp')
            out.element('format', {'pattern' : 'S', 'unit' : 'millisecond', 'property' : 'at.' + d.name})
            out.close('tstamp')
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name, 'millis' : '${at.' + d.name + '}0000'})
            out.element('echo', {'message' : d.name + ' touched to ${at.' + d.name + '}0000${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.element('sleep', {'seconds' : '3'})
            out.open('condition', {'property' : 'mx.' + d.name, 'value' : sys.executable})
            out.open('islastmodified', {'millis' : '${at.' + d.name + '}0000', 'mode' : 'equals'})
            out.element('file', {'file' : '${java.io.tmpdir}/' + d.name})
            out.close('islastmodified')
            out.close('condition')
            out.element('echo', {'message' : d.name + ' defined as ' + '${mx.' + d.name + '}${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.close('target')
            out.open('target', {'name' : 'packagelater-' + d.name, 'depends' : 'checkpackage-' + d.name, 'if' : 'mx.' + d.name})
            out.open('exec', {'executable' : '${mx.' + d.name + '}', 'failonerror' : 'true', 'dir' : execDir, 'output' : join(p.suite.get_output_root(), 'netbeans.log'), 'append' : 'true'})
            out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
            out.element('arg', {'value' : os.path.abspath(__file__)})
            out.element('arg', {'value' : 'build'})
            out.element('arg', {'value' : '-f'})
            out.element('arg', {'value' : '--only'})
            out.element('arg', {'value' : d.name})
            out.element('arg', {'value' : '--force-javac'})
            out.element('arg', {'value' : '--no-native'})
            out.element('arg', {'value' : '--no-daemon'})
            out.close('exec')
            out.close('target')
    dependsOn = ''
    sep = ''
    for d in dists:
        dependsOn = dependsOn + sep + 'packagelater-' + d.name
        sep = ','
    out.open('target', {'name' : 'packagelater', 'depends' : dependsOn})
    out.close('target')
    out.open('target', {'name' : 'jar', 'depends' : 'compile'})
    out.close('target')
    out.element('target', {'name' : 'test', 'depends' : 'run'})
    out.element('target', {'name' : 'test-single', 'depends' : 'run'})
    out.open('target', {'name' : 'run'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.element('target', {'name' : 'debug-test', 'depends' : 'debug'})
    out.open('target', {'name' : 'debug', 'depends' : '-mx-init'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('nbjpdastart', {'addressproperty' : 'jpda.address', 'name' : p.name})
    out.open('classpath')
    out.open('fileset', {'dir' : '..'})
    out.element('include', {'name' : '*/bin/'})
    out.close('fileset')
    out.close('classpath')
    out.open('sourcepath')
    out.element('pathelement', {'location' : 'src'})
    out.close('sourcepath')
    out.close('nbjpdastart')
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : '-d'})
    out.element('arg', {'value' : '--attach'})
    out.element('arg', {'value' : '${jpda.address}'})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'javadoc'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'javadoc'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.element('arg', {'value' : '--force'})
    out.close('exec')
    out.element('nbbrowse', {'file' : 'javadoc/index.html'})
    out.close('target')
    out.close('project')
    update_file(join(p.dir, 'build.xml'), out.xml(indent='\t', newl='\n'))
    if files is not None:
        files.append(join(p.dir, 'build.xml'))

    out = XMLDoc()
    out.open('project', {'xmlns' : 'http://www.netbeans.org/ns/project/1'})
    out.element('type', data='org.netbeans.modules.java.j2seproject')
    out.open('configuration')
    out.open('data', {'xmlns' : 'http://www.netbeans.org/ns/j2se-project/3'})
    out.element('name', data=p.name)
    out.element('explicit-platform', {'explicit-source-supported' : 'true'})
    out.open('source-roots')
    out.element('root', {'id' : 'src.dir'})
    if len(p.annotation_processors()) > 0:
        out.element('root', {'id' : 'src.ap-source-output.dir', 'name' : 'Generated Packages'})
    out.close('source-roots')
    out.open('test-roots')
    out.close('test-roots')
    out.close('data')

    firstDep = []

    def processDep(dep, edge):
        if dep is p:
            return

        if dep.isProject():
            n = dep.name.replace('.', '_')
            if not firstDep:
                out.open('references', {'xmlns' : 'http://www.netbeans.org/ns/ant-project-references/1'})
                firstDep.append(dep)

            out.open('reference')
            out.element('foreign-project', data=n)
            out.element('artifact-type', data='jar')
            out.element('script', data='build.xml')
            out.element('target', data='jar')
            out.element('clean-target', data='clean')
            out.element('id', data='jar')
            out.close('reference') #pylint: disable=too-many-function-args
    p.walk_deps(visit=processDep, ignoredEdges=[DEP_EXCLUDED])

    if firstDep:
        out.close('references')

    out.close('configuration')
    out.close('project')
    update_file(join(p.dir, 'nbproject', 'project.xml'), out.xml(indent='    ', newl='\n'))
    if files is not None:
        files.append(join(p.dir, 'nbproject', 'project.xml'))

    out = StringIO()
    jdkPlatform = 'JDK_' + str(jdk.version)

    annotationProcessorEnabled = "false"
    annotationProcessorSrcFolder = ""
    annotationProcessorSrcFolderRef = ""
    if len(p.annotation_processors()) > 0:
        annotationProcessorEnabled = "true"
        ensure_dir_exists(p.source_gen_dir())
        annotationProcessorSrcFolder = os.path.relpath(p.source_gen_dir(), p.dir)
        annotationProcessorSrcFolder = annotationProcessorSrcFolder.replace('\\', '\\\\')
        annotationProcessorSrcFolderRef = "src.ap-source-output.dir=" + annotationProcessorSrcFolder

    canSymlink = not (is_windows() or is_cygwin()) and 'symlink' in dir(os)
    if canSymlink:
        nbBuildDir = join(p.dir, 'nbproject', 'build')
        apSourceOutRef = "annotation.processing.source.output=" + annotationProcessorSrcFolder
        if os.path.lexists(nbBuildDir):
            os.unlink(nbBuildDir)
        os.symlink(p.output_dir(), nbBuildDir)
    else:
        nbBuildDir = p.output_dir()
        apSourceOutRef = ""
    ensure_dir_exists(p.output_dir())

    _copy_eclipse_settings(p)

    content = """
annotation.processing.enabled=""" + annotationProcessorEnabled + """
annotation.processing.enabled.in.editor=""" + annotationProcessorEnabled + """
""" + apSourceOutRef + """
annotation.processing.processors.list=
annotation.processing.run.all.processors=true
application.title=""" + p.name + """
application.vendor=mx
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterEnabled=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterLocation=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.enableFormatAsSaveAction=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.linefeed=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.preserveBreakPoints=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.SaveActionModifiedLinesOnly=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.showNotifications=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.sourcelevel=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectPref=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectSettings=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsEnabled=true
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsFile=nbproject/cfg_hints.xml
build.classes.dir=${build.dir}
build.classes.excludes=**/*.java,**/*.form
# This directory is removed when the project is cleaned:
build.dir=""" + nbBuildDir + """
$cos.update=package
$cos.update.resources=changed.files
compile.on.save=true
build.generated.sources.dir=${build.dir}/generated-sources
# Only compile against the classpath explicitly listed here:
build.sysclasspath=ignore
build.test.classes.dir=${build.dir}/test/classes
build.test.results.dir=${build.dir}/test/results
# Uncomment to specify the preferred debugger connection transport:
#debug.transport=dt_socket
debug.classpath=\\
${run.classpath}
debug.test.classpath=\\
${run.test.classpath}
# This directory is removed when the project is cleaned:
dist.dir=dist
dist.jar=${dist.dir}/""" + p.name + """.jar
dist.javadoc.dir=${dist.dir}/javadoc
endorsed.classpath=
excludes=
includes=**
jar.compress=false
java.main.action=test
# Space-separated list of extra javac options
javac.compilerargs=-XDignore.symbol.file
javac.deprecation=false
javac.source=""" + str(p.javaCompliance) + """
javac.target=""" + str(p.javaCompliance) + """
javac.test.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
javadoc.additionalparam=
javadoc.author=false
javadoc.encoding=${source.encoding}
javadoc.noindex=false
javadoc.nonavbar=false
javadoc.notree=false
javadoc.private=false
javadoc.splitindex=true
javadoc.use=true
javadoc.version=false
javadoc.windowtitle=
manifest.file=manifest.mf
meta.inf.dir=${src.dir}/META-INF
mkdist.disabled=false
platforms.""" + jdkPlatform + """.home=""" + jdk.home + """
platform.active=""" + jdkPlatform + """
run.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
# Space-separated list of JVM arguments used when running the project
# (you may also define separate properties like run-sys-prop.name=value instead of -Dname=value
# or test-sys-prop.name=value to set system properties for unit tests):
run.jvmargs=
run.test.classpath=\\
${javac.test.classpath}:\\
${build.test.classes.dir}
test.src.dir=./test
""" + annotationProcessorSrcFolderRef + """
source.encoding=UTF-8""".replace(':', os.pathsep).replace('/', os.sep)
    print(content, file=out)

    # Workaround for NetBeans "too clever" behavior. If you want to be
    # able to press F6 or Ctrl-F5 in NetBeans and run/debug unit tests
    # then the project must have its main.class property set to an
    # existing class with a properly defined main method. Until this
    # behavior is remedied, we specify a well known Truffle class
    # that will be on the class path for most Truffle projects.
    # This can be overridden by defining a netbeans.project.properties
    # attribute for a project in suite.py (see below).
    print("main.class=com.oracle.truffle.api.impl.Accessor", file=out)

    # Add extra properties specified in suite.py for this project
    if hasattr(p, 'netbeans.project.properties'):
        properties = getattr(p, 'netbeans.project.properties')
        for prop in [properties] if isinstance(properties, str) else properties:
            print(prop, file=out)

    mainSrc = True
    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        ensure_dir_exists(srcDir)
        ref = 'file.reference.' + p.name + '-' + src
        print(ref + '=' + src, file=out)
        if mainSrc:
            print('src.dir=${' + ref + '}', file=out)
            mainSrc = False
        else:
            print('src.' + src + '.dir=${' + ref + '}', file=out)

    javacClasspath = []

    def newDepsCollector(into):
        return lambda dep, edge: into.append(dep) if dep.isLibrary() or dep.isJdkLibrary() or dep.isProject() or dep.isClasspathDependency() else None

    deps = []
    p.walk_deps(visit=newDepsCollector(deps))
    annotationProcessorOnlyDeps = []
    if len(p.annotation_processors()) > 0:
        for apDep in p.annotation_processors():
            resolvedApDeps = []
            apDep.walk_deps(visit=newDepsCollector(resolvedApDeps))
            for resolvedApDep in resolvedApDeps:
                if not resolvedApDep in deps:
                    deps.append(resolvedApDep)
                    annotationProcessorOnlyDeps.append(resolvedApDep)

    annotationProcessorReferences = []

    for dep in deps:
        if dep == p:
            continue

        if dep.isLibrary() or dep.isJdkLibrary():
            if dep.isLibrary():
                path = dep.get_path(resolve=True)
                sourcePath = dep.get_source_path(resolve=True)
            else:
                path = dep.classpath_repr(jdk, resolve=True)
                sourcePath = dep.get_source_path(jdk)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
            if sourcePath:
                if os.sep == '\\':
                    sourcePath = sourcePath.replace('\\', '\\\\')
                print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)
        elif dep.isMavenProject():
            path = dep.get_path(resolve=False)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
        elif dep.isProject():
            n = dep.name.replace('.', '_')
            relDepPath = os.path.relpath(dep.dir, p.dir).replace(os.sep, '/')
            if canSymlink:
                depBuildPath = join('nbproject', 'build')
            else:
                depBuildPath = 'dist/' + dep.name + '.jar'
            ref = 'reference.' + n + '.jar'
            print('project.' + n + '=' + relDepPath, file=out)
            print(ref + '=${project.' + n + '}/' + depBuildPath, file=out)
        elif dep.isJreLibrary():
            continue
        elif dep.isClasspathDependency():
            extra = [di for di in dep.deps if di not in deps]
            if dep.isDistribution() and dep.deps and not extra:
                # ignore distribution classpath dependencies that only contain other explicit depedencies
                continue
            path = dep.classpath_repr(resolve=True)
            sourcePath = dep.get_source_path(jdk) if hasattr(dep, 'get_source_path') else None
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
                if sourcePath:
                    if os.sep == '\\':
                        sourcePath = sourcePath.replace('\\', '\\\\')
                    print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)

        if not dep in annotationProcessorOnlyDeps:
            javacClasspath.append('${' + ref + '}')
        else:
            annotationProcessorReferences.append('${' + ref + '}')

    print('javac.classpath=\\\n    ' + (os.pathsep + '\\\n    ').join(javacClasspath), file=out)
    print('javac.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.classpath}'] + annotationProcessorReferences), file=out)
    print('javac.test.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.test.classpath}'] + annotationProcessorReferences), file=out)

    update_file(join(p.dir, 'nbproject', 'project.properties'), out.getvalue())
    out.close()

    if files is not None:
        files.append(join(p.dir, 'nbproject', 'project.properties'))

    for source in p.suite.netbeans_settings_sources().get('cfg_hints.xml'):
        with open(source) as fp:
            content = fp.read()
    update_file(join(p.dir, 'nbproject', 'cfg_hints.xml'), content)

    if files is not None:
        files.append(join(p.dir, 'nbproject', 'cfg_hints.xml'))

def _netbeansinit_suite(args, suite, refreshOnly=False, buildProcessorJars=True):
    mxOutputDir = ensure_dir_exists(suite.get_mx_output_dir())
    configZip = TimeStampFile(join(mxOutputDir, 'netbeans-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if _check_ide_timestamp(suite, configZip, 'netbeans'):
        logv('[NetBeans configurations are up to date - skipping]')
        return

    files = []
    libFiles = []
    jdks = set()
    for p in suite.projects:
        if not p.isJavaProject():
            continue

        if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
            continue

        includedInDists = [d for d in suite.dists if p in d.archived_deps()]
        _netbeansinit_project(p, jdks, files, libFiles, includedInDists)
    log('If using NetBeans:')
    # http://stackoverflow.com/questions/24720665/cant-resolve-jdk-internal-package
    log('  1. Edit etc/netbeans.conf in your NetBeans installation and modify netbeans_default_options variable to include "-J-DCachingArchiveProvider.disableCtSym=true"')
    log('  2. Ensure that the following platform(s) are defined (Tools -> Java Platforms):')
    for jdk in jdks:
        log('        JDK_' + str(jdk.version))
    log('  3. Open/create a Project Group for the directory containing the projects (File -> Project Group -> New Group... -> Folder of Projects)')

    _zip_files(files, suite.dir, configZip.path)
    _zip_files(libFiles, suite.dir, configLibsZip)


# IntelliJ SDK types.
intellij_java_sdk_type = 'JavaSDK'
intellij_python_sdk_type = 'Python SDK'
intellij_ruby_sdk_type = 'RUBY_SDK'


@command('mx', 'intellijinit')
def intellijinit_cli(args):
    """(re)generate Intellij project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('--no-external-projects', action='store_false', dest='externalProjects', help='Do not generate external projects.')
    parser.add_argument('--no-java-projects', '--mx-python-modules-only', action='store_false', dest='javaModules', help='Do not generate projects for the java projects.')
    parser.add_argument('--native-projects', action='store_true', dest='nativeProjects', help='Generate native projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    intellijinit(args.remainder, mx_python_modules=args.pythonProjects, java_modules=args.javaModules,
                 generate_external_projects=args.externalProjects, native_projects=args.nativeProjects)


def intellijinit(args, refreshOnly=False, doFsckProjects=True, mx_python_modules=True, java_modules=True,
                 generate_external_projects=True, native_projects=False):
    # In a multiple suite context, the .idea directory in each suite
    # has to be complete and contain information that is repeated
    # in dependent suites.
    declared_modules = set()
    referenced_modules = set()
    sdks = intellij_read_sdks()
    for suite in suites(True) + ([_mx_suite] if mx_python_modules else []):
        _intellij_suite(args, suite, declared_modules, referenced_modules, sdks, refreshOnly, mx_python_modules,
                        generate_external_projects, java_modules and not suite.isBinarySuite(), suite != primary_suite(),
                        generate_native_projects=native_projects)

    if len(referenced_modules - declared_modules) != 0:
        abort('Some referenced modules are missing from modules.xml: {}'.format(referenced_modules - declared_modules))

    if mx_python_modules:
        # mx module
        moduleXml = XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in set((p.subDir for p in _mx_suite.projects if p.subDir)):
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        if dirname(_mx_suite.get_output_root()) == _mx_suite.dir:
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + basename(_mx_suite.get_output_root())})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        moduleXml.close('component')
        moduleXml.close('module')
        mxModuleFile = join(_mx_suite.dir, basename(_mx_suite.dir) + '.iml')
        update_file(mxModuleFile, moduleXml.xml(indent='  ', newl='\n'))

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

def intellij_read_sdks():
    sdks = dict()
    if is_linux() or is_openbsd() or is_sunos() or is_windows():
        xmlSdks = glob.glob(os.path.expanduser("~/.IdeaIC*/config/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.IntelliJIdea*/config/options/jdk.table.xml"))
    elif is_darwin():
        xmlSdks = glob.glob(os.path.expanduser("~/Library/Preferences/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Preferences/IntelliJIdea*/options/jdk.table.xml"))
    else:
        warn("Location of IntelliJ SDK definitions on {} is unknown".format(get_os()))
        return sdks
    if len(xmlSdks) == 0:
        warn("IntelliJ SDK definitions not found")
        return sdks

    verRE = re.compile(r'^.*[/\\]\.?(IntelliJIdea|IdeaIC)([^/\\]+)[/\\].*$')
    def verSort(path):
        match = verRE.match(path)
        return match.group(2) + (".a" if match.group(1) == "IntellijIC" else ".b")

    xmlSdks.sort(key=verSort)
    xmlSdk = xmlSdks[-1]  # Pick the most recent IntelliJ version, preferring Ultimate over Community edition.
    log("Using SDK definitions from {}".format(xmlSdk))

    versionRegexes = {}
    versionRegexes[intellij_java_sdk_type] = re.compile(r'^java\s+version\s+"([^"]+)"$|^([\d._]+)$')
    versionRegexes[intellij_python_sdk_type] = re.compile(r'^Python\s+(.+)$')
    versionRegexes[intellij_ruby_sdk_type] = re.compile(r'^ver\.([^\s]+)\s+.*$')

    for sdk in etreeParse(xmlSdk).getroot().findall("component[@name='ProjectJdkTable']/jdk[@version='2']"):
        name = sdk.find("name").get("value")
        kind = sdk.find("type").get("value")
        home = realpath(os.path.expanduser(sdk.find("homePath").get("value").replace('$USER_HOME$', '~')))
        if home.find('$APPLICATION_HOME_DIR$') != -1:
            # Don't know how to convert this into a real path so ignore it
            continue
        versionRE = versionRegexes.get(kind)
        if not versionRE or sdk.find("version") is None:
            # ignore unknown kinds
            continue

        match = versionRE.match(sdk.find("version").get("value"))
        if match:
            version = match.group(1)
            sdks[home] = {'name': name, 'type': kind, 'version': version}
            logv("Found SDK {} with values {}".format(home, sdks[home]))
        else:
            warn("Couldn't understand Java version specification \"{}\" for {} in {}".format(sdk.find("version").get("value"), home, xmlSdk))
    return sdks

def intellij_get_java_sdk_name(sdks, jdk):
    if jdk.home in sdks:
        sdk = sdks[jdk.home]
        if sdk['type'] == intellij_java_sdk_type:
            return sdk['name']
    return str(jdk.javaCompliance)

def intellij_get_python_sdk_name(sdks):
    exe = realpath(sys.executable)
    if exe in sdks:
        sdk = sdks[exe]
        if sdk['type'] == intellij_python_sdk_type:
            return sdk['name']
    return "Python {v[0]}.{v[1]} ({exe})".format(v=sys.version_info, exe=exe)

def intellij_get_ruby_sdk_name(sdks):
    for sdk in sdks.values():
        if sdk['type'] == intellij_ruby_sdk_type:
            return sdk['name']
    return "truffleruby"

_not_intellij_filename = re.compile(r'[^a-zA-Z0-9]')

def _intellij_library_file_name(library_name, unique_library_file_names):
    def _gen_name(n=None):
        suffix = '' if n is None else str(n)
        return _not_intellij_filename.sub('_', library_name) + suffix + '.xml'

    # Find a unique name like intellij does
    file_name = _gen_name()
    i = 2
    while file_name in unique_library_file_names:
        file_name = _gen_name(i)
        i += 1

    unique_library_file_names.add(file_name)
    return file_name


def _intellij_suite(args, s, declared_modules, referenced_modules, sdks, refreshOnly=False, mx_python_modules=False,
                    generate_external_projects=True, java_modules=True, module_files_only=False, generate_native_projects=False):
    libraries = set()
    jdk_libraries = set()

    ideaProjectDirectory = join(s.dir, '.idea')

    modulesXml = XMLDoc()
    if not module_files_only and not s.isBinarySuite():
        ensure_dir_exists(ideaProjectDirectory)
        nameFile = join(ideaProjectDirectory, '.name')
        update_file(nameFile, s.name)
        modulesXml.open('project', attributes={'version': '4'})
        modulesXml.open('component', attributes={'name': 'ProjectModuleManager'})
        modulesXml.open('modules')


    def _intellij_exclude_if_exists(xml, p, name, output=False):
        root = p.get_output_root() if output else p.dir
        path = join(root, name)
        if exists(path):
            excludeRoot = p.get_output_root() if output else '$MODULE_DIR$'
            excludePath = join(excludeRoot, name)
            xml.element('excludeFolder', attributes={'url':'file://' + excludePath})

    annotationProcessorProfiles = {}

    def _complianceToIntellijLanguageLevel(compliance):
        # they changed the name format starting with JDK_10
        if compliance.value >= 10:
            # Lastest Idea 2018.2 only understands JDK_11 so clamp at that value
            return 'JDK_' + str(min(compliance.value, 11))
        return 'JDK_1_' + str(compliance.value)

    def _intellij_external_project(externalProjects, sdks, host):
        if externalProjects:
            for project_name, project_definition in externalProjects.items():
                if not project_definition.get('path', None):
                    abort("external project {} is missing path attribute".format(project_name))
                if not project_definition.get('type', None):
                    abort("external project {} is missing type attribute".format(project_name))

                supported = ['path', 'type', 'source', 'test', 'excluded', 'load_path']
                unknown = set(project_definition.keys()) - frozenset(supported)
                if unknown:
                    abort("There are unsupported {} keys in {} external project".format(unknown, project_name))

                path = os.path.realpath(join(host.dir, project_definition["path"]))
                module_type = project_definition["type"]

                moduleXml = XMLDoc()
                moduleXml.open('module',
                               attributes={'type': {'ruby': 'RUBY_MODULE',
                                                    'python': 'PYTHON_MODULE',
                                                    'web': 'WEB_MODULE'}.get(module_type, 'UKNOWN_MODULE'),
                                           'version': '4'})
                moduleXml.open('component',
                               attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
                moduleXml.element('exclude-output')

                moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
                for name in project_definition.get('source', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(False)})
                for name in project_definition.get('test', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(True)})
                for name in project_definition.get('excluded', []):
                    _intellij_exclude_if_exists(moduleXml, type('', (object,), {"dir": path})(), name)
                moduleXml.close('content')

                if module_type == "ruby":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_ruby_sdk_type, 'jdkName': intellij_get_ruby_sdk_name(sdks)})
                elif module_type == "python":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
                elif module_type == "web":
                    # nothing to do
                    pass
                else:
                    abort("External project type {} not supported".format(module_type))

                moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
                moduleXml.close('component')

                load_paths = project_definition.get('load_path', [])
                if load_paths:
                    if not module_type == "ruby":
                        abort("load_path is supported only for ruby type external project")
                    moduleXml.open('component', attributes={'name': 'RModuleSettingsStorage'})
                    load_paths_attributes = {}
                    load_paths_attributes['number'] = str(len(load_paths))
                    for i, name in enumerate(load_paths):
                        load_paths_attributes["string" + str(i)] = "$MODULE_DIR$/" + name
                    moduleXml.element('LOAD_PATH', load_paths_attributes)
                    moduleXml.close('component')

                moduleXml.close('module')
                moduleFile = join(path, project_name + '.iml')
                update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

                if not module_files_only:
                    declared_modules.add(project_name)
                    moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                    modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

    if generate_external_projects:
        for p in s.projects_recursive() + _mx_suite.projects_recursive():
            _intellij_external_project(getattr(p, 'externalProjects', None), sdks, p)

    max_checkstyle_version = None
    compilerXml = None

    if java_modules:
        if not module_files_only:
            compilerXml = XMLDoc()
            compilerXml.open('project', attributes={'version': '4'})

        # The IntelliJ parser seems to mishandle empty ADDITIONAL_OPTIONS_OVERRIDE elements
        # so only emit the section if there will be something in it.
        additionalOptionsOverrides = False
        assert not s.isBinarySuite()
        # create the modules (1 IntelliJ module = 1 mx project/distribution)
        for p in s.projects_recursive() + _mx_suite.projects_recursive():
            if not p.isJavaProject():
                continue

            jdk = get_jdk(p.javaCompliance)
            assert jdk

            ensure_dir_exists(p.dir)

            processors = p.annotation_processors()
            if processors:
                annotationProcessorProfiles.setdefault((p.source_gen_dir_name(),) + tuple(processors), []).append(p)

            intellijLanguageLevel = _complianceToIntellijLanguageLevel(p.javaCompliance)

            moduleXml = XMLDoc()
            moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

            moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
            moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/' + p.output_dir(relative=True)})

            moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
            for src in p.srcDirs:
                srcDir = join(p.dir, src)
                ensure_dir_exists(srcDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + src, 'isTestSource': str(p.is_test_project())})
            for name in ['.externalToolBuilders', '.settings', 'nbproject']:
                _intellij_exclude_if_exists(moduleXml, p, name)
            moduleXml.close('content')

            if processors:
                moduleXml.open('content', attributes={'url': 'file://' + p.get_output_root()})
                genDir = p.source_gen_dir()
                ensure_dir_exists(genDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://' + p.source_gen_dir(), 'isTestSource': str(p.is_test_project()), 'generated': 'true'})
                for name in [basename(p.output_dir())]:
                    _intellij_exclude_if_exists(moduleXml, p, name, output=True)
                moduleXml.close('content')

            moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

            proj = p

            dependencies_project_packages = set()

            def should_process_dep(dep, edge):
                if dep.isTARDistribution() or dep.isNativeProject() or dep.isArchivableProject() or dep.isResourceLibrary():
                    logv("Ignoring dependency from {} to {}".format(proj.name, dep.name))
                    return False
                return True

            def process_dep(dep, edge):
                if dep is proj:
                    return
                if dep.isLibrary() or dep.isJARDistribution() or dep.isMavenProject():
                    libraries.add(dep)
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                elif dep.isJavaProject():
                    dependencies_project_packages.update(dep.defined_java_packages())
                    referenced_modules.add(dep.name)
                    moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep.name})
                elif dep.isJdkLibrary():
                    jdk_libraries.add(dep)
                    if jdk.javaCompliance < dep.jdkStandardizedSince:
                        moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                    else:
                        logv("{} skipping {} for {}".format(p, dep, jdk)) #pylint: disable=undefined-loop-variable
                elif dep.isJreLibrary():
                    pass
                elif dep.isClasspathDependency():
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                else:
                    abort("Dependency not supported: {0} ({1})".format(dep, dep.__class__.__name__))

            p.walk_deps(preVisit=should_process_dep, visit=process_dep, ignoredEdges=[DEP_EXCLUDED])

            moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_java_sdk_type, 'jdkName': intellij_get_java_sdk_name(sdks, jdk)})

            moduleXml.close('component')

            if compilerXml and jdk.javaCompliance >= '9':
                moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
                if moduleDeps:
                    exports = sorted([(m, pkgs) for m, pkgs in moduleDeps.items() if dependencies_project_packages.isdisjoint(pkgs)])
                    if exports:
                        args = []
                        exported_modules = set()
                        for m, pkgs in exports:
                            args += ['--add-exports={}/{}=ALL-UNNAMED'.format(m, pkg) for pkg in pkgs]
                            exported_modules.add(m)
                        roots = set(jdk.get_root_modules())
                        observable_modules = jdk.get_modules()
                        default_module_graph = get_transitive_closure(roots, observable_modules)
                        module_graph = get_transitive_closure(roots | exported_modules, observable_modules)
                        extra_modules = module_graph - default_module_graph
                        if extra_modules:
                            args.append('--add-modules=' + ','.join((m.name for m in extra_modules)))
                        if not additionalOptionsOverrides:
                            additionalOptionsOverrides = True
                            compilerXml.open('component', {'name': 'JavacSettings'})
                            compilerXml.open('option', {'name': 'ADDITIONAL_OPTIONS_OVERRIDE'})
                        compilerXml.element('module', {'name': p.name, 'options': ' '.join(args)})

            # Checkstyle
            csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
            if csConfig:
                max_checkstyle_version = max(max_checkstyle_version, VersionSpec(checkstyleVersion)) if max_checkstyle_version else VersionSpec(checkstyleVersion)

                moduleXml.open('component', attributes={'name': 'CheckStyle-IDEA-Module'})
                moduleXml.open('option', attributes={'name': 'configuration'})
                moduleXml.open('map')
                moduleXml.element('entry', attributes={'key': "checkstyle-version", 'value': checkstyleVersion})
                moduleXml.element('entry', attributes={'key': "active-configuration", 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})
                moduleXml.close('map')
                moduleXml.close('option')
                moduleXml.close('component')

            moduleXml.close('module')
            moduleFile = join(p.dir, p.name + '.iml')
            update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

            if not module_files_only:
                declared_modules.add(p.name)
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
        if additionalOptionsOverrides:
            compilerXml.close('option')
            compilerXml.close('component')

    if mx_python_modules:
        # mx.<suite> python module:
        moduleXml = XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in os.listdir(s.mxDir):
            directory = join(s.mxDir, d)
            if isdir(directory) and dir_contains_files_recursively(directory, r".*\.java"):
                moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        processes_suites = {s.name}

        def _mx_projects_suite(visited_suite, suite_import):
            if suite_import.name in processes_suites:
                return
            processes_suites.add(suite_import.name)
            dep_suite = suite(suite_import.name)
            moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': basename(dep_suite.mxDir)})
            moduleFile = join(dep_suite.mxDir, basename(dep_suite.mxDir) + '.iml')
            if not module_files_only:
                declared_modules.add(basename(dep_suite.mxDir))
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
            dep_suite.visit_imports(_mx_projects_suite)
        s.visit_imports(_mx_projects_suite)
        moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx'})
        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(s.mxDir, basename(s.mxDir) + '.iml')
        update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))
        if not module_files_only:
            declared_modules.add(basename(s.mxDir))
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

            declared_modules.add(basename(_mx_suite.dir))
            mxModuleFile = join(_mx_suite.dir, basename(_mx_suite.dir) + '.iml')
            mxModuleFilePath = "$PROJECT_DIR$/" + os.path.relpath(mxModuleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + mxModuleFilePath, 'filepath': mxModuleFilePath})

    if generate_native_projects:
        _intellij_native_projects(s, module_files_only, declared_modules, modulesXml)

    if generate_external_projects:
        _intellij_external_project(s.suiteDict.get('externalProjects', None), sdks, s)

    if not module_files_only:
        modulesXml.close('modules')
        modulesXml.close('component')
        modulesXml.close('project')
        moduleXmlFile = join(ideaProjectDirectory, 'modules.xml')
        update_file(moduleXmlFile, modulesXml.xml(indent='  ', newl='\n'))

    if java_modules and not module_files_only:
        unique_library_file_names = set()
        librariesDirectory = join(ideaProjectDirectory, 'libraries')

        ensure_dir_exists(librariesDirectory)

        def make_library(name, path, source_path, suite_dir):
            libraryXml = XMLDoc()

            libraryXml.open('component', attributes={'name': 'libraryTable'})
            libraryXml.open('library', attributes={'name': name})
            libraryXml.open('CLASSES')
            pathX = relpath_or_absolute(path, suite_dir, prefix='$PROJECT_DIR$')
            libraryXml.element('root', attributes={'url': 'jar://' + pathX + '!/'})
            libraryXml.close('CLASSES')
            libraryXml.element('JAVADOC')
            if sourcePath:
                libraryXml.open('SOURCES')
                if os.path.isdir(sourcePath):
                    sourcePathX = relpath_or_absolute(sourcePath, suite_dir, prefix='$PROJECT_DIR$')
                    libraryXml.element('root', attributes={'url': 'file://' + sourcePathX})
                else:
                    source_pathX = relpath_or_absolute(source_path, suite_dir, prefix='$PROJECT_DIR$')
                    libraryXml.element('root', attributes={'url': 'jar://' + source_pathX + '!/'})
                libraryXml.close('SOURCES')
            else:
                libraryXml.element('SOURCES')
            libraryXml.close('library')
            libraryXml.close('component')

            libraryFile = join(librariesDirectory, _intellij_library_file_name(name, unique_library_file_names))
            return update_file(libraryFile, libraryXml.xml(indent='  ', newl='\n'))

        # Setup the libraries that were used above
        for library in libraries:
            sourcePath = None
            if library.isLibrary():
                path = library.get_path(True)
                if library.sourcePath:
                    sourcePath = library.get_source_path(True)
            elif library.isMavenProject():
                path = library.get_path(True)
                sourcePath = library.get_source_path(True)
            elif library.isJARDistribution():
                path = library.path
                if library.sourcesPath:
                    sourcePath = library.sourcesPath
            elif library.isClasspathDependency():
                path = library.classpath_repr()
            else:
                abort('Dependency not supported: {} ({})'.format(library.name, library.__class__.__name__))
            make_library(library.name, path, sourcePath, s.dir)

        jdk = get_jdk()
        updated = False
        for library in jdk_libraries:
            if library.classpath_repr(jdk) is not None:
                if make_library(library.name, library.classpath_repr(jdk), library.get_source_path(jdk), s.dir):
                    updated = True
        if jdk_libraries and updated:
            log("Setting up JDK libraries using {0}".format(jdk))

        # Set annotation processor profiles up, and link them to modules in compiler.xml

        compilerXml.open('component', attributes={'name': 'CompilerConfiguration'})

        compilerXml.element('option', attributes={'name': "DEFAULT_COMPILER", 'value': 'Javac'})
        # using the --release option with javac interferes with using --add-modules which is required for some projects
        compilerXml.element('option', attributes={'name': "USE_RELEASE_OPTION", 'value': 'false'})
        compilerXml.element('resourceExtensions')
        compilerXml.open('wildcardResourcePatterns')
        compilerXml.element('entry', attributes={'name': '!?*.java'})
        compilerXml.close('wildcardResourcePatterns')
        if annotationProcessorProfiles:
            compilerXml.open('annotationProcessing')
            for t, modules in sorted(annotationProcessorProfiles.items()):
                source_gen_dir = t[0]
                processors = t[1:]
                compilerXml.open('profile', attributes={'default': 'false', 'name': '-'.join([ap.name for ap in processors]) + "-" + source_gen_dir, 'enabled': 'true'})
                compilerXml.element('sourceOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.element('sourceTestOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.open('processorPath', attributes={'useClasspath': 'false'})

                # IntelliJ supports both directories and jars on the annotation processor path whereas
                # Eclipse only supports jars.
                for apDep in processors:
                    def processApDep(dep, edge):
                        if dep.isLibrary() or dep.isJARDistribution():
                            compilerXml.element('entry', attributes={'name': relpath_or_absolute(dep.path, s.dir, prefix='$PROJECT_DIR$')})
                        elif dep.isProject():
                            compilerXml.element('entry', attributes={'name': relpath_or_absolute(dep.output_dir(), s.dir, prefix='$PROJECT_DIR$')})
                    apDep.walk_deps(visit=processApDep)
                compilerXml.close('processorPath')
                for module in modules:
                    compilerXml.element('module', attributes={'name': module.name})
                compilerXml.close('profile')
            compilerXml.close('annotationProcessing')

        compilerXml.close('component')

    if compilerXml:
        compilerXml.close('project')
        compilerFile = join(ideaProjectDirectory, 'compiler.xml')
        update_file(compilerFile, compilerXml.xml(indent='  ', newl='\n'))

    if not module_files_only:
        # Write misc.xml for global JDK config
        miscXml = XMLDoc()
        miscXml.open('project', attributes={'version' : '4'})

        if java_modules:
            mainJdk = get_jdk()
            miscXml.open('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'languageLevel': _complianceToIntellijLanguageLevel(mainJdk.javaCompliance), 'project-jdk-name': intellij_get_java_sdk_name(sdks, mainJdk), 'project-jdk-type': intellij_java_sdk_type})
            miscXml.element('output', attributes={'url' : 'file://$PROJECT_DIR$/' + os.path.relpath(s.get_output_root(), s.dir)})
            miscXml.close('component')
        else:
            miscXml.element('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'project-jdk-name': intellij_get_python_sdk_name(sdks), 'project-jdk-type': intellij_python_sdk_type})

        miscXml.close('project')
        miscFile = join(ideaProjectDirectory, 'misc.xml')
        update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        # Generate a default configuration for debugging Graal
        runConfig = XMLDoc()
        runConfig.open('component', attributes={'name' : 'ProjectRunConfigurationManager'})
        runConfig.open('configuration', attributes={'default' :'false', 'name' : 'GraalDebug', 'type' : 'Remote', 'factoryName': 'Remote'})
        runConfig.element('option', attributes={'name' : 'USE_SOCKET_TRANSPORT', 'value' : 'true'})
        runConfig.element('option', attributes={'name' : 'SERVER_MODE', 'value' : 'false'})
        runConfig.element('option', attributes={'name' : 'SHMEM_ADDRESS', 'value' : 'javadebug'})
        runConfig.element('option', attributes={'name' : 'HOST', 'value' : 'localhost'})
        runConfig.element('option', attributes={'name' : 'PORT', 'value' : '8000'})
        runConfig.open('RunnerSettings', attributes={'RunnerId' : 'Debug'})
        runConfig.element('option', attributes={'name' : 'DEBUG_PORT', 'value' : '8000'})
        runConfig.element('option', attributes={'name' : 'LOCAL', 'value' : 'false'})
        runConfig.close('RunnerSettings')
        runConfig.element('method')
        runConfig.close('configuration')
        runConfig.close('component')
        runConfigFile = join(ideaProjectDirectory, 'runConfigurations', 'GraalDebug.xml')
        ensure_dir_exists(join(ideaProjectDirectory, 'runConfigurations'))
        update_file(runConfigFile, runConfig.xml(indent='  ', newl='\n'))

        if java_modules:
            # Eclipse formatter config
            corePrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.core.prefs')
            uiPrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.ui.prefs')
            if corePrefsSources:
                miscXml = XMLDoc()
                miscXml.open('project', attributes={'version' : '4'})
                out = StringIO()
                print('# GENERATED -- DO NOT EDIT', file=out)
                for source in corePrefsSources:
                    print('# Source:', source, file=out)
                    with open(source) as fileName:
                        for line in fileName:
                            if line.startswith('org.eclipse.jdt.core.formatter.'):
                                print(line.strip(), file=out)
                formatterConfigFile = join(ideaProjectDirectory, 'EclipseCodeFormatter.prefs')
                update_file(formatterConfigFile, out.getvalue())
                importConfigFile = None
                if uiPrefsSources:
                    out = StringIO()
                    print('# GENERATED -- DO NOT EDIT', file=out)
                    for source in uiPrefsSources:
                        print('# Source:', source, file=out)
                        with open(source) as fileName:
                            for line in fileName:
                                if line.startswith('org.eclipse.jdt.ui.importorder') \
                                        or line.startswith('org.eclipse.jdt.ui.ondemandthreshold') \
                                        or line.startswith('org.eclipse.jdt.ui.staticondemandthreshold'):
                                    print(line.strip(), file=out)
                    importConfigFile = join(ideaProjectDirectory, 'EclipseImports.prefs')
                    update_file(importConfigFile, out.getvalue())
                miscXml.open('component', attributes={'name' : 'EclipseCodeFormatterProjectSettings'})
                miscXml.open('option', attributes={'name' : 'projectSpecificProfile'})
                miscXml.open('ProjectSpecificProfile')
                miscXml.element('option', attributes={'name' : 'formatter', 'value' : 'ECLIPSE'})
                custom_eclipse_exe = get_env('ECLIPSE_EXE')
                if custom_eclipse_exe:
                    custom_eclipse = dirname(custom_eclipse_exe)
                    if is_darwin():
                        custom_eclipse = join(dirname(custom_eclipse), 'Eclipse', 'plugins')
                    if not exists(custom_eclipse_exe):
                        abort('Custom eclipse "{}" does not exist'.format(custom_eclipse_exe))
                    miscXml.element('option', attributes={'name' : 'eclipseVersion', 'value' : 'CUSTOM'})
                    miscXml.element('option', attributes={'name' : 'pathToEclipse', 'value' : custom_eclipse})
                miscXml.element('option', attributes={'name' : 'pathToConfigFileJava', 'value' : '$PROJECT_DIR$/.idea/' + basename(formatterConfigFile)})
                if importConfigFile:
                    miscXml.element('option', attributes={'name' : 'importOrderConfigFilePath', 'value' : '$PROJECT_DIR$/.idea/' + basename(importConfigFile)})
                    miscXml.element('option', attributes={'name' : 'importOrderFromFile', 'value' : 'true'})

                miscXml.close('ProjectSpecificProfile')
                miscXml.close('option')
                miscXml.close('component')
                miscXml.close('project')
                miscFile = join(ideaProjectDirectory, 'eclipseCodeFormatter.xml')
                update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        if java_modules:
            # Write checkstyle-idea.xml for the CheckStyle-IDEA
            checkstyleXml = XMLDoc()
            checkstyleXml.open('project', attributes={'version': '4'})
            checkstyleXml.open('component', attributes={'name': 'CheckStyle-IDEA'})
            checkstyleXml.open('option', attributes={'name' : "configuration"})
            checkstyleXml.open('map')

            if max_checkstyle_version:
                checkstyleXml.element('entry', attributes={'key': "checkstyle-version", 'value': str(max_checkstyle_version)})

            # Initialize an entry for each style that is used
            checkstyleConfigs = set([])
            for p in s.projects_recursive():
                if not p.isJavaProject():
                    continue
                csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
                if not csConfig or csConfig in checkstyleConfigs:
                    continue
                checkstyleConfigs.add(csConfig)
                checkstyleXml.element('entry', attributes={'key' : "location-" + str(len(checkstyleConfigs)), 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})

            checkstyleXml.close('map')
            checkstyleXml.close('option')
            checkstyleXml.close('component')
            checkstyleXml.close('project')
            checkstyleFile = join(ideaProjectDirectory, 'checkstyle-idea.xml')
            update_file(checkstyleFile, checkstyleXml.xml(indent='  ', newl='\n'))

            # mx integration
            def antTargetName(dist):
                return 'archive_' + dist.name

            def artifactFileName(dist):
                return dist.name.replace('.', '_').replace('-', '_') + '.xml'
            validDistributions = [dist for dist in sorted_dists() if not dist.suite.isBinarySuite() and not dist.isTARDistribution()]

            # 1) Make an ant file for archiving the distributions.
            antXml = XMLDoc()
            antXml.open('project', attributes={'name': s.name, 'default': 'archive'})
            for dist in validDistributions:
                antXml.open('target', attributes={'name': antTargetName(dist)})
                antXml.open('exec', attributes={'executable': sys.executable})
                antXml.element('arg', attributes={'value': join(_mx_home, 'mx.py')})
                antXml.element('arg', attributes={'value': 'archive'})
                antXml.element('arg', attributes={'value': '@' + dist.name})
                antXml.close('exec')
                antXml.close('target')

            antXml.close('project')
            antFile = join(ideaProjectDirectory, 'ant-mx-archive.xml')
            update_file(antFile, antXml.xml(indent='  ', newl='\n'))

            # 2) Tell IDEA that there is an ant-build.
            ant_mx_archive_xml = 'file://$PROJECT_DIR$/.idea/ant-mx-archive.xml'
            metaAntXml = XMLDoc()
            metaAntXml.open('project', attributes={'version': '4'})
            metaAntXml.open('component', attributes={'name': 'AntConfiguration'})
            metaAntXml.open('buildFile', attributes={'url': ant_mx_archive_xml})
            metaAntXml.close('buildFile')
            metaAntXml.close('component')
            metaAntXml.close('project')
            metaAntFile = join(ideaProjectDirectory, 'ant.xml')
            update_file(metaAntFile, metaAntXml.xml(indent='  ', newl='\n'))

            # 3) Make an artifact for every distribution
            validArtifactNames = {artifactFileName(dist) for dist in validDistributions}
            artifactsDir = join(ideaProjectDirectory, 'artifacts')
            ensure_dir_exists(artifactsDir)
            for fileName in os.listdir(artifactsDir):
                filePath = join(artifactsDir, fileName)
                if os.path.isfile(filePath) and fileName not in validArtifactNames:
                    os.remove(filePath)

            for dist in validDistributions:
                artifactXML = XMLDoc()
                artifactXML.open('component', attributes={'name': 'ArtifactManager'})
                artifactXML.open('artifact', attributes={'build-on-make': 'true', 'name': dist.name})
                artifactXML.open('output-path', data='$PROJECT_DIR$/mxbuild/artifacts/' + dist.name)
                artifactXML.close('output-path')
                artifactXML.open('properties', attributes={'id': 'ant-postprocessing'})
                artifactXML.open('options', attributes={'enabled': 'true'})
                artifactXML.open('file', data=ant_mx_archive_xml)
                artifactXML.close('file')
                artifactXML.open('target', data=antTargetName(dist))
                artifactXML.close('target')
                artifactXML.close('options')
                artifactXML.close('properties')
                artifactXML.open('root', attributes={'id': 'root'})
                for javaProject in [dep for dep in dist.archived_deps() if dep.isJavaProject()]:
                    artifactXML.element('element', attributes={'id': 'module-output', 'name': javaProject.name})
                for javaProject in [dep for dep in dist.deps if dep.isLibrary() or dep.isDistribution()]:
                    artifactXML.element('element', attributes={'id': 'artifact', 'artifact-name': javaProject.name})
                artifactXML.close('root')
                artifactXML.close('artifact')
                artifactXML.close('component')

                artifactFile = join(artifactsDir, artifactFileName(dist))
                update_file(artifactFile, artifactXML.xml(indent='  ', newl='\n'))

        def intellij_scm_name(vc_kind):
            if vc_kind == 'git':
                return 'Git'
            elif vc_kind == 'hg':
                return 'hg4idea'

        vcsXml = XMLDoc()
        vcsXml.open('project', attributes={'version': '4'})
        vcsXml.open('component', attributes={'name': 'VcsDirectoryMappings'})

        suites_for_vcs = suites() + ([_mx_suite] if mx_python_modules else [])
        sourceSuitesWithVCS = [vc_suite for vc_suite in suites_for_vcs if vc_suite.isSourceSuite() and vc_suite.vc is not None]
        uniqueSuitesVCS = {(vc_suite.vc_dir, vc_suite.vc.kind) for vc_suite in sourceSuitesWithVCS}
        for vcs_dir, kind in uniqueSuitesVCS:
            vcsXml.element('mapping', attributes={'directory': vcs_dir, 'vcs': intellij_scm_name(kind)})

        vcsXml.close('component')
        vcsXml.close('project')

        vcsFile = join(ideaProjectDirectory, 'vcs.xml')
        update_file(vcsFile, vcsXml.xml(indent='  ', newl='\n'))

        # TODO look into copyright settings


def _intellij_native_projects(s, module_files_only, declared_modules, modulesXml):
    for p in s.projects_recursive() + _mx_suite.projects_recursive():
        if not p.isNativeProject():
            continue

        ensure_dir_exists(p.dir)

        moduleXml = XMLDoc()
        moduleXml.open('module', attributes={'type': 'CPP_MODULE'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'false'})

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            ensure_dir_exists(srcDir)
            moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$/' + src,
                                                          'isTestSource': str(p.is_test_project())})
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(p.dir, p.name + '.iml')
        update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

        if not module_files_only:
            declared_modules.add(p.name)
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

### ~~~~~~~~~~~~~ IDE, IntelliJ

def ideclean(args):
    """remove all IDE project configurations"""
    def rm(path):
        if exists(path):
            os.remove(path)

    for s in suites() + [_mx_suite]:
        rm(join(s.get_mx_output_dir(), 'eclipse-config.zip'))
        rm(join(s.get_mx_output_dir(), 'netbeans-config.zip'))
        shutil.rmtree(join(s.dir, '.idea'), ignore_errors=True)

    for p in projects() + _mx_suite.projects:
        if not p.isJavaProject():
            continue

        shutil.rmtree(join(p.dir, '.settings'), ignore_errors=True)
        shutil.rmtree(join(p.dir, '.externalToolBuilders'), ignore_errors=True)
        shutil.rmtree(join(p.dir, 'nbproject'), ignore_errors=True)
        rm(join(p.dir, '.classpath'))
        rm(join(p.dir, '.checkstyle'))
        rm(join(p.dir, '.project'))
        rm(join(p.dir, '.factorypath'))
        rm(join(p.dir, p.name + '.iml'))
        rm(join(p.dir, 'build.xml'))
        rm(join(p.dir, 'eclipse-build.xml'))
        try:
            rm(join(p.dir, p.name + '.jar'))
        except:
            log_error("Error removing {0}".format(p.name + '.jar'))

    for d in _dists.values():
        if not d.isJARDistribution():
            continue
        if d.get_ide_project_dir():
            shutil.rmtree(d.get_ide_project_dir(), ignore_errors=True)

def ideinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate IDE project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    mx_ide = os.environ.get('MX_IDE', 'all').lower()
    all_ides = mx_ide == 'all'
    if all_ides or mx_ide == 'eclipse':
        eclipseinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False, pythonProjects=args.pythonProjects)
    if all_ides or mx_ide == 'netbeans':
        netbeansinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False)
    if all_ides or mx_ide == 'intellij':
        intellijinit(args.remainder, refreshOnly=refreshOnly, doFsckProjects=False, mx_python_modules=args.pythonProjects)
    if not refreshOnly:
        fsckprojects([])

def fsckprojects(args):
    """find directories corresponding to deleted Java projects and delete them"""
    for suite in suites(True, includeBinary=False):
        projectDirs = [p.dir for p in suite.projects]
        distIdeDirs = [d.get_ide_project_dir() for d in suite.dists if d.isJARDistribution() and d.get_ide_project_dir() is not None]
        for dirpath, dirnames, files in os.walk(suite.dir):
            if dirpath == suite.dir:
                # no point in traversing vc metadata dir, lib, .workspace
                # if there are nested source suites must not scan those now, as they are not in projectDirs (but contain .project files)
                omitted = [suite.mxDir, 'lib', '.workspace', 'mx.imports']
                if suite.vc:
                    omitted.append(suite.vc.metadir())
                dirnames[:] = [d for d in dirnames if d not in omitted]
            elif dirpath == suite.get_output_root():
                # don't want to traverse output dir
                dirnames[:] = []
            elif dirpath == suite.mxDir:
                # don't want to traverse mx.name as it contains a .project
                dirnames[:] = []
            elif dirpath in projectDirs:
                # don't traverse subdirs of an existing project in this suite
                dirnames[:] = []
            elif dirpath in distIdeDirs:
                # don't traverse subdirs of an existing distribution in this suite
                dirnames[:] = []
            else:
                maybe_project = basename(dirpath)
                if not _removedDeps.get(maybe_project):
                    projectConfigFiles = frozenset(['.classpath', '.project', 'nbproject', maybe_project + '.iml'])
                    indicators = projectConfigFiles.intersection(files)
                    if len(indicators) != 0:
                        indicators = [os.path.relpath(join(dirpath, i), suite.vc_dir) for i in indicators]
                        indicatorsInVC = suite.vc.locate(suite.vc_dir, indicators)
                        # Only proceed if there are indicator files that are not under VC
                        if len(indicators) > len(indicatorsInVC):
                            if ask_yes_no(dirpath + ' looks like a removed project -- delete it', 'n'):
                                shutil.rmtree(dirpath)
                                log('Deleted ' + dirpath)
        ideaProjectDirectory = join(suite.dir, '.idea')
        librariesDirectory = join(ideaProjectDirectory, 'libraries')
        if exists(librariesDirectory):
            neededLibraries = set()
            unique_library_file_names = set()
            for p in suite.projects_recursive() + _mx_suite.projects_recursive():
                if not p.isJavaProject():
                    continue
                def processDep(dep, edge):
                    if dep is p:
                        return
                    if dep.isLibrary() or dep.isJARDistribution() or dep.isJdkLibrary() or dep.isMavenProject() or dep.isClasspathDependency():
                        neededLibraries.add(dep)
                p.walk_deps(visit=processDep, ignoredEdges=[DEP_EXCLUDED])
            neededLibraryFiles = frozenset([_intellij_library_file_name(l.name, unique_library_file_names) for l in neededLibraries])
            existingLibraryFiles = frozenset(os.listdir(librariesDirectory))
            for library_file in existingLibraryFiles - neededLibraryFiles:
                file_path = join(librariesDirectory, library_file)
                relative_file_path = os.path.relpath(file_path, os.curdir)
                if ask_yes_no(relative_file_path + ' looks like a removed library -- delete it', 'n'):
                    os.remove(file_path)
                    log('Deleted ' + relative_file_path)


def verifysourceinproject(args):
    """find any Java source files that are outside any known Java projects

    Returns the number of suites with requireSourceInProjects == True that have Java sources not in projects.
    """
    unmanagedSources = {}
    suiteDirs = set()
    suiteVcDirs = {}
    suiteWhitelists = {}

    def ignorePath(path, whitelist):
        if whitelist is None:
            return True
        for entry in whitelist:
            if fnmatch.fnmatch(path, entry):
                return True
        return False

    for suite in suites(True, includeBinary=False):
        projectDirs = [p.dir for p in suite.projects]
        distIdeDirs = [d.get_ide_project_dir() for d in suite.dists if d.isJARDistribution() and d.get_ide_project_dir() is not None]
        suiteDirs.add(suite.dir)
        # all suites in the same repository must have the same setting for requiresSourceInProjects
        if suiteVcDirs.get(suite.vc_dir) is None:
            suiteVcDirs[suite.vc_dir] = suite.vc
            whitelistFile = join(suite.vc_dir, '.nonprojectsources')
            if exists(whitelistFile):
                with open(whitelistFile) as fp:
                    suiteWhitelists[suite.vc_dir] = [l.strip() for l in fp.readlines()]

        whitelist = suiteWhitelists.get(suite.vc_dir)
        for dirpath, dirnames, files in os.walk(suite.dir):
            if dirpath == suite.dir:
                # no point in traversing vc metadata dir, lib, .workspace
                # if there are nested source suites must not scan those now, as they are not in projectDirs (but contain .project files)
                omitted = [suite.mxDir, 'lib', '.workspace', 'mx.imports']
                if suite.vc:
                    omitted.append(suite.vc.metadir())
                dirnames[:] = [d for d in dirnames if d not in omitted]
            elif dirpath == suite.get_output_root():
                # don't want to traverse output dir
                dirnames[:] = []
                continue
            elif dirpath == suite.mxDir:
                # don't want to traverse mx.name as it contains a .project
                dirnames[:] = []
                continue
            elif dirpath in projectDirs:
                # don't traverse subdirs of an existing project in this suite
                dirnames[:] = []
                continue
            elif dirpath in distIdeDirs:
                # don't traverse subdirs of an existing distribution in this suite
                dirnames[:] = []
                continue
            elif 'pom.xml' in files:
                # skip maven suites
                dirnames[:] = []
                continue
            elif ignorePath(os.path.relpath(dirpath, suite.vc_dir), whitelist):
                # skip whitelisted directories
                dirnames[:] = []
                continue

            javaSources = [x for x in files if x.endswith('.java')]
            if len(javaSources) != 0:
                javaSources = [os.path.relpath(join(dirpath, i), suite.vc_dir) for i in javaSources]
                javaSourcesInVC = [x for x in suite.vc.locate(suite.vc_dir, javaSources) if not ignorePath(x, whitelist)]
                if len(javaSourcesInVC) > 0:
                    unmanagedSources.setdefault(suite.vc_dir, []).extend(javaSourcesInVC)

    # also check for files that are outside of suites
    for vcDir, vc in suiteVcDirs.items():
        for dirpath, dirnames, files in os.walk(vcDir):
            if dirpath in suiteDirs:
                # skip known suites
                dirnames[:] = []
            elif exists(join(dirpath, 'mx.' + basename(dirpath), 'suite.py')):
                # skip unknown suites
                dirnames[:] = []
            elif 'pom.xml' in files:
                # skip maven suites
                dirnames[:] = []
            else:
                javaSources = [x for x in files if x.endswith('.java')]
                if len(javaSources) != 0:
                    javaSources = [os.path.relpath(join(dirpath, i), vcDir) for i in javaSources]
                    javaSourcesInVC = [x for x in vc.locate(vcDir, javaSources) if not ignorePath(x, whitelist)]
                    if len(javaSourcesInVC) > 0:
                        unmanagedSources.setdefault(vcDir, []).extend(javaSourcesInVC)

    retcode = 0
    if len(unmanagedSources) > 0:
        log('The following files are managed but not in any project:')
        for vc_dir, sources in unmanagedSources.items():
            for source in sources:
                log(source)
            if suiteWhitelists.get(vc_dir) is not None:
                retcode += 1
                log('Since {} has a .nonprojectsources file, all Java source files must be \n'\
                    'part of a project in a suite or the files must be listed in the .nonprojectsources.'.format(vc_dir))

    return retcode

def _find_packages(project, onlyPublic=True, included=None, excluded=None):
    """
    Finds the set of packages defined by a project.

    :param JavaProject project: the Java project to process
    :param bool onlyPublic: specifies if only packages containing a ``package-info.java`` file are to be considered
    :param set included: if not None or empty, only consider packages in this set
    :param set excluded: if not None or empty, do not consider packages in this set
    """
    sourceDirs = project.source_dirs()
    def is_visible(name):
        if onlyPublic:
            return name == 'package-info.java'
        else:
            return name.endswith('.java')
    packages = set()
    for sourceDir in sourceDirs:
        for root, _, files in os.walk(sourceDir):
            if len([name for name in files if is_visible(name)]) != 0:
                package = root[len(sourceDir) + 1:].replace(os.sep, '.')
                if not included or package in included:
                    if not excluded or package not in excluded:
                        packages.add(package)
    return packages

_javadocRefNotFound = re.compile("Tag @link(plain)?: reference not found: ")

def javadoc(args, parser=None, docDir='javadoc', includeDeps=True, stdDoclet=True, mayBuild=True, quietForNoPackages=False):
    """generate javadoc for some/all Java projects"""

    parser = ArgumentParser(prog='mx javadoc') if parser is None else parser
    parser.add_argument('-d', '--base', action='store', help='base directory for output')
    parser.add_argument('--unified', action='store_true', help='put javadoc in a single directory instead of one per project')
    parser.add_argument('--implementation', action='store_true', help='include also implementation packages')
    parser.add_argument('--force', action='store_true', help='(re)generate javadoc even if package-list file exists')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--argfile', action='store', help='name of file containing extra javadoc options')
    parser.add_argument('--arg', action='append', dest='extra_args', help='extra Javadoc arguments (e.g. --arg @-use)', metavar='@<arg>', default=[])
    parser.add_argument('-m', '--memory', action='store', help='-Xmx value to pass to underlying JVM')
    parser.add_argument('--packages', action='store', help='comma separated packages to process (omit to process all packages)')
    parser.add_argument('--exclude-packages', action='store', help='comma separated packages to exclude')
    parser.add_argument('--allow-warnings', action='store_true', help='Exit normally even if warnings were found')

    args = parser.parse_args(args)

    # build list of projects to be processed
    if args.projects is not None:
        partialJavadoc = True
        candidates = [project(name) for name in args.projects.split(',')]
    else:
        partialJavadoc = False
        candidates = projects_opt_limit_to_suites()

    # optionally restrict packages within a project
    include_packages = None
    if args.packages is not None:
        include_packages = frozenset(args.packages.split(','))

    exclude_packages = None
    if args.exclude_packages is not None:
        exclude_packages = frozenset(args.exclude_packages.split(','))

    def outDir(p):
        if args.base is None:
            return join(p.dir, docDir)
        return join(args.base, p.name, docDir)

    def check_package_list(p):
        return not exists(join(outDir(p), 'package-list'))

    def assess_candidate(p, projects):
        if p in projects:
            return False, 'Already visited'
        if not args.implementation and p.is_test_project():
            return False, 'Test project'
        if args.force or args.unified or check_package_list(p):
            projects.append(p)
            return True, None
        return False, 'package-list file exists'

    projects = []
    """ :type: list[JavaProject]"""
    snippetsPatterns = set()
    verifySincePresent = []
    for p in candidates:
        if p.isJavaProject():
            if hasattr(p.suite, 'snippetsPattern'):
                snippetsPatterns.add(p.suite.snippetsPattern)
                if p.suite.primary:
                    verifySincePresent = p.suite.getMxCompatibility().verifySincePresent()
            if includeDeps:
                p.walk_deps(visit=lambda dep, edge: assess_candidate(dep, projects)[0] if dep.isJavaProject() else None)
            added, reason = assess_candidate(p, projects)
            if not added:
                logv('[{0} - skipping {1}]'.format(reason, p.name))
    snippets = []
    for s in set((p.suite for p in projects)):
        assert isinstance(s, SourceSuite)
        for p in s.projects:
            if p.isJavaProject():
                snippets += p.source_dirs()
    snippets = os.pathsep.join(snippets)
    snippetslib = library('CODESNIPPET-DOCLET').get_path(resolve=True)


    ap = []
    for sp in snippetsPatterns:
        ap += ['-snippetclasses', sp]

    snippetsPatterns = ap

    if not projects:
        log('All projects were skipped.')
        if not _opts.verbose:
            log('Re-run with global -v option to see why.')
        return

    extraArgs = [a.lstrip('@') for a in args.extra_args]
    if args.argfile is not None:
        extraArgs += ['@' + args.argfile]
    memory = '2g'
    if args.memory is not None:
        memory = args.memory
    memory = '-J-Xmx' + memory

    if mayBuild:
        # The project must be built to ensure javadoc can find class files for all referenced classes
        build(['--no-native', '--dependencies', ','.join((p.name for p in projects))])
    if not args.unified:
        for p in projects:
            assert p.isJavaProject()
            pkgs = _find_packages(p, False, include_packages, exclude_packages)
            jdk = get_jdk(p.javaCompliance)
            links = ['-linkoffline', 'http://docs.oracle.com/javase/' + str(jdk.javaCompliance.value) + '/docs/api/', _mx_home + '/javadoc/jdk']
            out = outDir(p)
            def visit(dep, edge):
                if dep == p:
                    return
                if dep.isProject():
                    depOut = outDir(dep)
                    links.append('-link')
                    links.append(os.path.relpath(depOut, out))
            p.walk_deps(visit=visit)
            cp = classpath(p.name, includeSelf=True, jdk=jdk)
            sp = os.pathsep.join(p.source_dirs())
            overviewFile = join(p.dir, 'overview.html')
            delOverviewFile = False
            if not exists(overviewFile):
                with open(overviewFile, 'w') as fp:
                    print('<html><body>Documentation for the <code>' + p.name + '</code> project.</body></html>', file=fp)
                delOverviewFile = True
            nowarnAPI = []
            if not args.warnAPI:
                nowarnAPI.append('-XDignore.symbol.file')

            if not pkgs:
                if quietForNoPackages:
                    return
                else:
                    abort('No packages to generate javadoc for!')

            # windowTitle onloy applies to the standard doclet processor
            windowTitle = []
            if stdDoclet:
                windowTitle = ['-windowtitle', p.name + ' javadoc']
            try:
                log('Generating {2} for {0} in {1}'.format(p.name, out, docDir))

                # Once https://bugs.openjdk.java.net/browse/JDK-8041628 is fixed,
                # this should be reverted to:
                # javadocExe = get_jdk().javadoc
                # we can then also respect _opts.relatex_compliance
                javadocExe = jdk.javadoc

                run([javadocExe, memory,
                     '-XDignore.symbol.file',
                     '-classpath', cp,
                     '-quiet',
                     '-notimestamp',
                     '-d', out,
                     '-overview', overviewFile,
                     '-sourcepath', sp,
                     '-doclet', 'org.apidesign.javadoc.codesnippet.Doclet',
                     '-docletpath', snippetslib,
                     '-snippetpath', snippets,
                     '-hiddingannotation', 'java.lang.Deprecated',
                     '-source', str(jdk.javaCompliance)] +
                     snippetsPatterns +
                     jdk.javadocLibOptions([]) +
                     ([] if jdk.javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
                     links +
                     extraArgs +
                     nowarnAPI +
                     windowTitle +
                     list(pkgs))
                logv('Generated {2} for {0} in {1}'.format(p.name, out, docDir))
            finally:
                if delOverviewFile:
                    os.remove(overviewFile)

    else:
        jdk = get_jdk()
        pkgs = set()
        sproots = []
        names = []
        classpath_deps = set()

        for p in projects:
            pkgs.update(_find_packages(p, not args.implementation, include_packages, exclude_packages))
            sproots += p.source_dirs()
            names.append(p.name)
            for dep in p.deps:
                if dep.isJavaProject():
                    if dep not in projects:
                        classpath_deps.add(dep)
                elif dep.isLibrary() or dep.isJARDistribution() or dep.isMavenProject() or dep.isJdkLibrary():
                    classpath_deps.add(dep)
                elif dep.isJreLibrary():
                    pass
                elif dep.isTARDistribution() or dep.isNativeProject() or dep.isArchivableProject():
                    logv("Ignoring dependency from {} to {}".format(p.name, dep.name))
                else:
                    abort("Dependency not supported: {0} ({1})".format(dep, dep.__class__.__name__))

        links = ['-linkoffline', 'http://docs.oracle.com/javase/' + str(jdk.javaCompliance.value) + '/docs/api/', _mx_home + '/javadoc/jdk']
        overviewFile = os.sep.join([primary_suite().dir, primary_suite().name, 'overview.html'])
        out = join(primary_suite().dir, docDir)
        if args.base is not None:
            out = join(args.base, docDir)
        cp = classpath(classpath_deps, jdk=jdk)
        sp = os.pathsep.join(sproots)
        nowarnAPI = []
        if not args.warnAPI:
            nowarnAPI.append('-XDignore.symbol.file')

        def find_group(pkg):
            for p in sproots:
                info = p + os.path.sep + pkg.replace('.', os.path.sep) + os.path.sep + 'package-info.java'
                if exists(info):
                    f = open(info, "r")
                    for line in f:
                        m = re.search('group="(.*)"', line)
                        if m:
                            return m.group(1)
            return None
        groups = OrderedDict()
        for p in pkgs:
            g = find_group(p)
            if g is None:
                continue
            if g not in groups:
                groups[g] = set()
            groups[g].add(p)
        groupargs = list()
        for k, v in groups.items():
            if len(v) == 0:
                continue
            groupargs.append('-group')
            groupargs.append(k)
            groupargs.append(':'.join(v))

        if not pkgs:
            if quietForNoPackages:
                return
            else:
                abort('No packages to generate javadoc for!')

        log('Generating {2} for {0} in {1}'.format(', '.join(names), out, docDir))

        ignoreWarnings = set()
        if jdk.javaCompliance >= JavaCompliance('9'):
            # JDK9+ reports codesnippetdoclet is using JDK8's Javadoc API
            ignoreWarnings.add('javadoc: warning - The old Doclet and Taglet APIs in the packages')
            ignoreWarnings.add('com.sun.javadoc, com.sun.tools.doclets and their implementations')
            ignoreWarnings.add('are planned to be removed in a future JDK release. These')
            ignoreWarnings.add('components have been superseded by the new APIs in jdk.javadoc.doclet.')
            ignoreWarnings.add('Users are strongly recommended to migrate to the new APIs.')

        class WarningCapture:
            def __init__(self, prefix, forward, ignoreBrokenRefs):
                self.prefix = prefix
                self.forward = forward
                self.ignoreBrokenRefs = ignoreBrokenRefs
                self.warnings = 0

            def __call__(self, msg):
                if msg.rstrip() in ignoreWarnings:
                    return
                shouldPrint = self.forward
                if ': warning - ' in msg:
                    if not self.ignoreBrokenRefs or not _javadocRefNotFound.search(msg):
                        self.warnings += 1
                        shouldPrint = not args.allow_warnings
                    else:
                        shouldPrint = False
                if shouldPrint:
                    warn(self.prefix + msg.rstrip('\r\n'))
                else:
                    logv(self.prefix + msg.rstrip('\r\n'))

        captureOut = WarningCapture('stdout: ', False, partialJavadoc)
        captureErr = WarningCapture('stderr: ', True, partialJavadoc)

        run([get_jdk().javadoc, memory,
             '-classpath', cp,
             '-quiet',
             '-notimestamp',
             '-d', out,
             '-doclet', 'org.apidesign.javadoc.codesnippet.Doclet',
             '-docletpath', snippetslib,
             '-snippetpath', snippets,
             '-hiddingannotation', 'java.lang.Deprecated',
             '-sourcepath', sp] +
             verifySincePresent +
             snippetsPatterns +
             (['-J--add-opens=jdk.javadoc/com.sun.tools.javadoc.main=ALL-UNNAMED'] if jdk.javaCompliance >= JavaCompliance('9') else []) +
             ([] if jdk.javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
             (['-overview', overviewFile] if exists(overviewFile) else []) +
             groupargs +
             links +
             extraArgs +
             nowarnAPI +
             list(pkgs), True, captureOut, captureErr)

        if not args.allow_warnings and captureErr.warnings:
            abort('Error: Warnings in the javadoc are not allowed!')
        if args.allow_warnings and not captureErr.warnings:
            logv("Warnings were allowed but there was none")

        logv('Generated {2} for {0} in {1}'.format(', '.join(names), out, docDir))

def site(args):
    """creates a website containing javadoc and the project dependency graph"""

    parser = ArgumentParser(prog='site')
    parser.add_argument('-d', '--base', action='store', help='directory for generated site', required=True, metavar='<dir>')
    parser.add_argument('--tmp', action='store', help='directory to use for intermediate results', metavar='<dir>')
    parser.add_argument('--name', action='store', help='name of overall documentation', required=True, metavar='<name>')
    parser.add_argument('--overview', action='store', help='path to the overview content for overall documentation', required=True, metavar='<path>')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--jd', action='append', help='extra Javadoc arguments (e.g. --jd @-use)', metavar='@<arg>', default=[])
    parser.add_argument('--exclude-packages', action='store', help='comma separated packages to exclude', metavar='<pkgs>')
    parser.add_argument('--dot-output-base', action='store', help='base file name (relative to <dir>/all) for project dependency graph .svg and .jpg files generated by dot (omit to disable dot generation)', metavar='<path>')
    parser.add_argument('--title', action='store', help='value used for -windowtitle and -doctitle javadoc args for overall documentation (default: "<name>")', metavar='<title>')
    args = parser.parse_args(args)

    args.base = os.path.abspath(args.base)
    tmpbase = args.tmp if args.tmp else mkdtemp(prefix=basename(args.base) + '.', dir=dirname(args.base))
    unified = join(tmpbase, 'all')

    exclude_packages_arg = []
    if args.exclude_packages is not None:
        exclude_packages_arg = ['--exclude-packages', args.exclude_packages]

    projects_arg = []
    if args.projects is not None:
        projects_arg = ['--projects', args.projects]
        projects = [project(name) for name in args.projects.split(',')]
    else:
        projects = []
        walk_deps(visit=lambda dep, edge: projects.append(dep) if dep.isProject() else None, ignoredEdges=[DEP_EXCLUDED])

    extra_javadoc_args = []
    for a in args.jd:
        extra_javadoc_args.append('--arg')
        extra_javadoc_args.append('@' + a)

    try:
        # Create javadoc for each project
        javadoc(['--base', tmpbase] + exclude_packages_arg + projects_arg + extra_javadoc_args)

        # Create unified javadoc for all projects
        with open(args.overview) as fp:
            content = fp.read()
            idx = content.rfind('</body>')
            if idx != -1:
                args.overview = join(tmpbase, 'overview_with_projects.html')
                with open(args.overview, 'w') as fp2:
                    print(content[0:idx], file=fp2)
                    print("""<div class="contentContainer">, file=fp2
<table class="overviewSummary" border="0" cellpadding="3" cellspacing="0" summary="Projects table">
<caption><span>Projects</span><span class="tabEnd">&nbsp;</span></caption>
<tr><th class="colFirst" scope="col">Project</th><th class="colLast" scope="col">&nbsp;</th></tr>
<tbody>""")
                    color = 'row'
                    for p in projects:
                        print('<tr class="{1}Color"><td class="colFirst"><a href="../{0}/javadoc/index.html",target = "_top">{0}</a></td><td class="colLast">&nbsp;</td></tr>'.format(p.name, color), file=fp2)
                        color = 'row' if color == 'alt' else 'alt'

                    print('</tbody></table></div>', file=fp2)
                    print(content[idx:], file=fp2)

        title = args.title if args.title is not None else args.name
        javadoc(['--base', tmpbase,
                 '--unified',
                 '--arg', '@-windowtitle', '--arg', '@' + title,
                 '--arg', '@-doctitle', '--arg', '@' + title,
                 '--arg', '@-overview', '--arg', '@' + args.overview] + exclude_packages_arg + projects_arg + extra_javadoc_args)

        if exists(unified):
            shutil.rmtree(unified)
        os.rename(join(tmpbase, 'javadoc'), unified)

        # Generate dependency graph with Graphviz
        if args.dot_output_base is not None:
            dotErr = None
            try:
                if 'version' not in _check_output_str(['dot', '-V'], stderr=subprocess.STDOUT):
                    dotErr = 'dot -V does not print a string containing "version"'
            except subprocess.CalledProcessError as e:
                dotErr = 'error calling "dot -V": {0}'.format(e)
            except OSError as e:
                dotErr = 'error calling "dot -V": {0}'.format(e)

            if dotErr is not None:
                abort('cannot generate dependency graph: ' + dotErr)

            dot = join(tmpbase, 'all', str(args.dot_output_base) + '.dot')
            svg = join(tmpbase, 'all', str(args.dot_output_base) + '.svg')
            jpg = join(tmpbase, 'all', str(args.dot_output_base) + '.jpg')
            html = join(tmpbase, 'all', str(args.dot_output_base) + '.html')
            with open(dot, 'w') as fp:
                dim = len(projects)
                print('digraph projects {', file=fp)
                print('rankdir=BT;', file=fp)
                print('size = "' + str(dim) + ',' + str(dim) + '";', file=fp)
                print('node [shape=rect, fontcolor="blue"];', file=fp)
                # print('edge [color="green"];', file=fp)
                for p in projects:
                    print('"' + p.name + '" [URL = "../' + p.name + '/javadoc/index.html", target = "_top"]', file=fp)
                    for dep in p.canonical_deps():
                        if dep in [proj.name for proj in projects]:
                            print('"' + p.name + '" -> "' + dep + '"', file=fp)
                depths = dict()
                for p in projects:
                    d = p.max_depth()
                    depths.setdefault(d, list()).append(p.name)
                print('}', file=fp)

            run(['dot', '-Tsvg', '-o' + svg, '-Tjpg', '-o' + jpg, dot])

            # Post-process generated SVG to remove title elements which most browsers
            # render as redundant (and annoying) tooltips.
            with open(svg, 'r') as fp:
                content = fp.read()
            content = re.sub('<title>.*</title>', '', content)
            content = re.sub('xlink:title="[^"]*"', '', content)
            with open(svg, 'w') as fp:
                fp.write(content)

            # Create HTML that embeds the svg file in an <object> frame
            with open(html, 'w') as fp:
                print('<html><body><object data="{0}.svg" type="image/svg+xml"></object></body></html>'.format(args.dot_output_base), file=fp)


        if args.tmp:
            copytree(tmpbase, args.base)
        else:
            shutil.move(tmpbase, args.base)

        print('Created website - root is ' + join(args.base, 'all', 'index.html'))

    finally:
        if not args.tmp and exists(tmpbase):
            rmtree(tmpbase)

def _kwArg(kwargs):
    if len(kwargs) > 0:
        return kwargs.pop(0)
    return None

@suite_context_free
def sclone(args):
    """clone a suite repository, and its imported suites"""
    parser = ArgumentParser(prog='mx sclone')
    parser.add_argument('--source', help='url/path of repo containing suite', metavar='<url>')
    parser.add_argument('--subdir', help='sub-directory containing the suite in the repository (suite name)')
    parser.add_argument('--dest', help='destination directory (default basename of source)', metavar='<path>')
    parser.add_argument('--revision', help='revision to checkout')
    parser.add_argument("--no-imports", action='store_true', help='do not clone imported suites')
    parser.add_argument("--kind", help='vc kind for URL suites', default='hg')
    parser.add_argument('--ignore-version', action='store_true', help='ignore version mismatch for existing suites')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)

    warn("The sclone command is deprecated and is scheduled for removal.")

    # check for non keyword args
    if args.source is None:
        args.source = _kwArg(args.nonKWArgs)
    if args.dest is None:
        args.dest = _kwArg(args.nonKWArgs)
    if len(args.nonKWArgs) > 0:
        abort('unrecognized args: ' + ' '.join(args.nonKWArgs))

    if args.source is None:
        # must be primary suite and dest is required
        if primary_suite() is None:
            abort('--source missing and no primary suite found')
        if args.dest is None:
            abort('--dest required when --source is not given')
        source = primary_suite().vc_dir
        if source != primary_suite().dir:
            subdir = os.path.relpath(source, primary_suite().dir)
            if args.subdir and args.subdir != subdir:
                abort("--subdir should be '{}'".format(subdir))
            args.subdir = subdir
    else:
        source = args.source

    if args.dest is not None:
        dest = args.dest
    else:
        dest = basename(source.rstrip('/'))
        if dest.endswith('.git'):
            dest = dest[:-len('.git')]

    dest = os.path.abspath(dest)
    dest_dir = join(dest, args.subdir) if args.subdir else dest
    source = mx_urlrewrites.rewriteurl(source)
    vc = vc_system(args.kind)
    vc.clone(source, dest=dest)
    mxDir = _is_suite_dir(dest_dir)
    if not mxDir:
        warn("'{}' is not an mx suite".format(dest_dir))
        return
    _discover_suites(mxDir, load=False, register=False)


@suite_context_free
def scloneimports(args):
    """clone the imports of an existing suite"""
    parser = ArgumentParser(prog='mx scloneimports')
    parser.add_argument('--source', help='path to primary suite')
    parser.add_argument('--manual', action='store_true', help='this option has no effect, it is deprecated')
    parser.add_argument('--ignore-version', action='store_true', help='ignore version mismatch for existing suites')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source')
    args = parser.parse_args(args)

    warn("The scloneimports command is deprecated and is scheduled for removal.")

    # check for non keyword args
    if args.source is None:
        args.source = _kwArg(args.nonKWArgs)
    if not args.source:
        abort('scloneimports: path to primary suite missing')
    if not os.path.isdir(args.source):
        abort(args.source + ' is not a directory')

    if args.nonKWArgs:
        warn("Some extra arguments were ignored: " + ' '.join((pipes.quote(a) for a in args.nonKWArgs)))

    if args.manual:
        warn("--manual argument is deprecated and has been ignored")
    if args.ignore_version:
        _opts.version_conflict_resolution = 'ignore'

    source = realpath(args.source)
    mxDir = _is_suite_dir(source)
    if not mxDir:
        abort("'{}' is not an mx suite".format(source))
    _discover_suites(mxDir, load=False, register=False, update_existing=True)


def _supdate_import_visitor(s, suite_import, **extra_args):
    _supdate(suite(suite_import.name), suite_import)


def _supdate(s, suite_import):
    s.visit_imports(_supdate_import_visitor)
    s.vc.update(s.vc_dir)


@no_suite_loading
def supdate(args):
    """update primary suite and all its imports"""
    parser = ArgumentParser(prog='mx supdate')
    args = parser.parse_args(args)

    _supdate(primary_suite(), None)

def _sbookmark_visitor(s, suite_import):
    imported_suite = suite(suite_import.name)
    if isinstance(imported_suite, SourceSuite):
        imported_suite.vc.bookmark(imported_suite.vc_dir, s.name + '-import', suite_import.version)


@no_suite_loading
def sbookmarkimports(args):
    """place bookmarks on the imported versions of suites in version control"""
    parser = ArgumentParser(prog='mx sbookmarkimports')
    parser.add_argument('--all', action='store_true', help='operate on all suites (default: primary suite only)')
    args = parser.parse_args(args)
    if args.all:
        for s in suites():
            s.visit_imports(_sbookmark_visitor)
    else:
        primary_suite().visit_imports(_sbookmark_visitor)


def _scheck_imports_visitor(s, suite_import, bookmark_imports, ignore_uncommitted):
    """scheckimports visitor for Suite.visit_imports"""
    _scheck_imports(s, suite(suite_import.name), suite_import, bookmark_imports, ignore_uncommitted)

def _scheck_imports(importing_suite, imported_suite, suite_import, bookmark_imports, ignore_uncommitted):
    importedVersion = imported_suite.version()
    if imported_suite.isDirty() and not ignore_uncommitted:
        msg = 'uncommitted changes in {}, please commit them and re-run scheckimports'.format(imported_suite.name)
        if isinstance(imported_suite, SourceSuite) and imported_suite.vc and imported_suite.vc.kind == 'hg':
            msg = '{}\nIf the only uncommitted change is an updated imported suite version, then you can run:\n\nhg -R {} commit -m "updated imported suite version"'.format(msg, imported_suite.vc_dir)
        abort(msg)
    if importedVersion != suite_import.version and suite_import.version is not None:
        print('imported version of {} in {} ({}) does not match parent ({})'.format(imported_suite.name, importing_suite.name, suite_import.version, importedVersion))
        if exists(importing_suite.suite_py()) and ask_yes_no('Update ' + importing_suite.suite_py()):
            with open(importing_suite.suite_py()) as fp:
                contents = fp.read()
            if contents.count(str(suite_import.version)) == 1:
                newContents = contents.replace(suite_import.version, str(importedVersion))
                if not update_file(importing_suite.suite_py(), newContents, showDiff=True):
                    abort("Updating {} failed: update didn't change anything".format(importing_suite.suite_py()))
                suite_import.version = importedVersion
                if bookmark_imports:
                    _sbookmark_visitor(importing_suite, suite_import)
            else:
                print('Could not update as the substring {} does not appear exactly once in {}'.format(suite_import.version, importing_suite.suite_py()))


@no_suite_loading
def scheckimports(args):
    """check that suite import versions are up to date"""
    parser = ArgumentParser(prog='mx scheckimports')
    parser.add_argument('-b', '--bookmark-imports', action='store_true', help="keep the import bookmarks up-to-date when updating the suites.py file")
    parser.add_argument('-i', '--ignore-uncommitted', action='store_true', help="Ignore uncommitted changes in the suite")
    parsed_args = parser.parse_args(args)
    # check imports of all suites
    for s in suites():
        s.visit_imports(_scheck_imports_visitor, bookmark_imports=parsed_args.bookmark_imports, ignore_uncommitted=parsed_args.ignore_uncommitted)
    _suitemodel.verify_imports(suites(), args)


@no_suite_discovery
def sforceimports(args):
    """force working directory revision of imported suites to match primary suite imports"""
    parser = ArgumentParser(prog='mx sforceimports')
    parser.add_argument('--strict-versions', action='store_true', help='DEPRECATED/IGNORED strict version checking')
    args = parser.parse_args(args)
    if args.strict_versions:
        warn("'--strict-versions' argument is deprecated and ignored. For version conflict resolution, see mx's '--version-conflict-resolution' flag.")
    _discover_suites(primary_suite().mxDir, load=False, register=False, update_existing=True)


def _spull_import_visitor(s, suite_import, update_versions, only_imports, update_all, no_update):
    """pull visitor for Suite.visit_imports"""
    _spull(s, suite(suite_import.name), suite_import, update_versions, only_imports, update_all, no_update)


def _spull(importing_suite, imported_suite, suite_import, update_versions, only_imports, update_all, no_update):
    # suite_import is None if importing_suite is primary suite
    primary = suite_import is None
    # proceed top down to get any updated version ids first

    if not primary or not only_imports:
        # skip pull of primary if only_imports = True
        vcs = imported_suite.vc
        # by default we pull to the revision id in the import, but pull head if update_versions = True
        rev = suite_import.version if not update_versions and suite_import and suite_import.version else None
        if rev and vcs.kind != suite_import.kind:
            abort('Wrong VC type for {} ({}), expecting {}, got {}'.format(imported_suite.name, imported_suite.dir, suite_import.kind, imported_suite.vc.kind))
        vcs.pull(imported_suite.vc_dir, rev, update=not no_update)

    if not primary and update_versions:
        importedVersion = vcs.parent(imported_suite.vc_dir)
        if importedVersion != suite_import.version:
            if exists(importing_suite.suite_py()):
                with open(importing_suite.suite_py()) as fp:
                    contents = fp.read()
                if contents.count(str(suite_import.version)) == 1:
                    newContents = contents.replace(suite_import.version, str(importedVersion))
                    log('Updating "version" attribute in import of suite ' + suite_import.name + ' in ' + importing_suite.suite_py() + ' to ' + importedVersion)
                    update_file(importing_suite.suite_py(), newContents, showDiff=True)
                else:
                    log('Could not update as the substring {} does not appear exactly once in {}'.format(suite_import.version, importing_suite.suite_py()))
                    log('Please update "version" attribute in import of suite ' + suite_import.name + ' in ' + importing_suite.suite_py() + ' to ' + importedVersion)
            suite_import.version = importedVersion

    imported_suite.re_init_imports()
    if not primary and not update_all:
        update_versions = False
    imported_suite.visit_imports(_spull_import_visitor, update_versions=update_versions, only_imports=only_imports, update_all=update_all, no_update=no_update)


@no_suite_loading
def spull(args):
    """pull primary suite and all its imports"""
    parser = ArgumentParser(prog='mx spull')
    parser.add_argument('--update-versions', action='store_true', help='pull tip of directly imported suites and update suite.py')
    parser.add_argument('--update-all', action='store_true', help='pull tip of all imported suites (transitively)')
    parser.add_argument('--only-imports', action='store_true', help='only pull imported suites, not the primary suite')
    parser.add_argument('--no-update', action='store_true', help='only pull, without updating')
    args = parser.parse_args(args)

    warn("The spull command is deprecated and is scheduled for removal.")

    if args.update_all and not args.update_versions:
        abort('--update-all can only be used in conjuction with --update-versions')

    _spull(primary_suite(), primary_suite(), None, args.update_versions, args.only_imports, args.update_all, args.no_update)


def _sincoming_import_visitor(s, suite_import, **extra_args):
    _sincoming(suite(suite_import.name), suite_import)


def _sincoming(s, suite_import):
    s.visit_imports(_sincoming_import_visitor)

    output = s.vc.incoming(s.vc_dir)
    if output:
        print(output)


@no_suite_loading
def sincoming(args):
    """check incoming for primary suite and all imports"""
    parser = ArgumentParser(prog='mx sincoming')
    args = parser.parse_args(args)

    warn("The sincoming command is deprecated and is scheduled for removal.")

    _sincoming(primary_suite(), None)

### ~~~~~~~~~~~~~ Mercurial

def _hg_command_import_visitor(s, suite_import, **extra_args):
    _hg_command(suite(suite_import.name), suite_import, **extra_args)


def _hg_command(s, suite_import, **extra_args):
    s.visit_imports(_hg_command_import_visitor, **extra_args)

    if isinstance(s.vc, HgConfig):
        out = s.vc.hg_command(s.vc_dir, extra_args['args'])
        print(out)


@no_suite_loading
def hg_command(args):
    """Run a Mercurial command in every suite"""

    warn("The hg command is deprecated and is scheduled for removal.")
    _hg_command(primary_suite(), None, args=args)


def _stip_import_visitor(s, suite_import, **extra_args):
    _stip(suite(suite_import.name), suite_import)


def _stip(s, suite_import):
    s.visit_imports(_stip_import_visitor)

    print('tip of ' + s.name + ': ' + s.vc.tip(s.vc_dir))


@no_suite_loading
def stip(args):
    """check tip for primary suite and all imports"""
    parser = ArgumentParser(prog='mx stip')
    args = parser.parse_args(args)

    warn("The tip command is deprecated and is scheduled for removal.")

    _stip(primary_suite(), None)


def _sversions_rev(rev, isdirty, with_color):
    if with_color:
        label = colorize(rev[0:12], color='yellow')
    else:
        label = rev[0:12]
    return label + ' +'[int(isdirty)]


@no_suite_loading
def sversions(args):
    """print working directory revision for primary suite and all imports"""
    parser = ArgumentParser(prog='mx sversions')
    parser.add_argument('--color', action='store_true', help='color the short form part of the revision id')
    args = parser.parse_args(args)
    with_color = args.color
    visited = set()

    def _sversions_import_visitor(s, suite_import, **extra_args):
        _sversions(suite(suite_import.name), suite_import)

    def _sversions(s, suite_import):
        if s.dir in visited:
            return
        visited.add(s.dir)
        if s.vc is None:
            print('No version control info for suite ' + s.name)
        else:
            print(_sversions_rev(s.vc.parent(s.vc_dir), s.vc.isDirty(s.vc_dir), with_color) + ' ' + s.name + ' ' + s.vc_dir)
        s.visit_imports(_sversions_import_visitor)

    if not isinstance(primary_suite(), MXSuite):
        _sversions(primary_suite(), None)

### ~~~~~~~~~~~~~ Java Compiler

def findclass(args, logToConsole=True, resolve=True, matcher=lambda string, classname: string in classname):
    """find all classes matching a given substring"""
    matches = []
    for entry, filename in classpath_walk(includeBootClasspath=True, resolve=resolve, jdk=get_jdk()):
        if filename.endswith('.class'):
            if isinstance(entry, zipfile.ZipFile):
                classname = filename.replace('/', '.')
            else:
                classname = filename.replace(os.sep, '.')
            classname = classname[:-len('.class')]
            for a in args:
                if matcher(a, classname):
                    if classname not in matches:
                        matches.append(classname)
                        if logToConsole:
                            log(classname)
    return matches

def select_items(items, descriptions=None, allowMultiple=True):
    """
    Presents a command line interface for selecting one or more (if allowMultiple is true) items.

    """
    if len(items) <= 1:
        return items
    else:
        assert is_interactive()
        numlen = str(len(str(len(items))))
        if allowMultiple:
            log(('[{0:>' + numlen + '}] <all>').format(0))
        for i in range(0, len(items)):
            if descriptions is None:
                log(('[{0:>' + numlen + '}] {1}').format(i + 1, items[i]))
            else:
                assert len(items) == len(descriptions)
                wrapper = textwrap.TextWrapper(subsequent_indent='    ')
                log('\n'.join(wrapper.wrap(('[{0:>' + numlen + '}] {1} - {2}').format(i + 1, items[i], descriptions[i]))))
        while True:
            if allowMultiple:
                s = input('Enter number(s) of selection (separate multiple choices with spaces): ').split()
            else:
                s = [input('Enter number of selection: ')]
            try:
                s = [int(x) for x in s]
            except:
                log('Selection contains non-numeric characters: "' + ' '.join(s) + '"')
                continue

            if allowMultiple and 0 in s:
                return items

            indexes = []
            for n in s:
                if n not in range(1, len(items) + 1):
                    log('Invalid selection: ' + str(n))
                    continue
                else:
                    indexes.append(n - 1)
            if allowMultiple:
                return [items[i] for i in indexes]
            if len(indexes) == 1:
                return items[indexes[0]]
            return None

def exportlibs(args):
    """export libraries to an archive file"""

    parser = ArgumentParser(prog='exportlibs')
    parser.add_argument('-b', '--base', action='store', help='base name of archive (default: libs)', default='libs', metavar='<path>')
    parser.add_argument('-a', '--include-all', action='store_true', help="include all defined libaries")
    parser.add_argument('--arc', action='store', choices=['tgz', 'tbz2', 'tar', 'zip'], default='tgz', help='the type of the archive to create')
    parser.add_argument('--no-sha1', action='store_false', dest='sha1', help='do not create SHA1 signature of archive')
    parser.add_argument('--no-md5', action='store_false', dest='md5', help='do not create MD5 signature of archive')
    parser.add_argument('--include-system-libs', action='store_true', help='include system libraries (i.e., those not downloaded from URLs)')
    parser.add_argument('extras', nargs=REMAINDER, help='extra files and directories to add to archive', metavar='files...')
    args = parser.parse_args(args)

    def createArchive(addMethod):
        entries = {}
        def add(path, arcname):
            apath = os.path.abspath(path)
            if arcname not in entries:
                entries[arcname] = apath
                logv('[adding ' + path + ']')
                addMethod(path, arcname=arcname)
            elif entries[arcname] != apath:
                logv('[warning: ' + apath + ' collides with ' + entries[arcname] + ' as ' + arcname + ']')
            else:
                logv('[already added ' + path + ']')

        libsToExport = set()
        if args.include_all:
            for lib in _libs.values():
                libsToExport.add(lib)
        else:
            def isValidLibrary(dep):
                if dep in _libs.keys():
                    lib = _libs[dep]
                    if len(lib.urls) != 0 or args.include_system_libs:
                        return lib
                return None

            # iterate over all project dependencies and find used libraries
            for p in _projects.values():
                for dep in p.deps:
                    r = isValidLibrary(dep)
                    if r:
                        libsToExport.add(r)

            # a library can have other libraries as dependency
            size = 0
            while size != len(libsToExport):
                size = len(libsToExport)
                for lib in libsToExport.copy():
                    for dep in lib.deps:
                        r = isValidLibrary(dep)
                        if r:
                            libsToExport.add(r)

        for lib in libsToExport:
            add(lib.get_path(resolve=True), lib.path)
            if lib.sha1:
                add(lib.get_path(resolve=True) + ".sha1", lib.path + ".sha1")
            if lib.sourcePath:
                add(lib.get_source_path(resolve=True), lib.sourcePath)
                if lib.sourceSha1:
                    add(lib.get_source_path(resolve=True) + ".sha1", lib.sourcePath + ".sha1")

        if args.extras:
            for e in args.extras:
                if os.path.isdir(e):
                    for root, _, filenames in os.walk(e):
                        for name in filenames:
                            f = join(root, name)
                            add(f, f)
                else:
                    add(e, e)

    if args.arc == 'zip':
        path = args.base + '.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            createArchive(zf.write)
    else:
        path = args.base + '.tar'
        mode = 'w'
        if args.arc != 'tar':
            sfx = args.arc[1:]
            mode = mode + ':' + sfx
            path = path + '.' + sfx
        with tarfile.open(path, mode) as tar:
            createArchive(tar.add)
    log('created ' + path)

    def digest(enabled, path, factory, suffix):
        if enabled:
            d = factory()
            with open(path, 'rb') as f:
                while True:
                    buf = f.read(4096)
                    if not buf:
                        break
                    d.update(buf)
            with open(path + '.' + suffix, 'w') as fp:
                print(d.hexdigest(), file=fp)
            log('created ' + path + '.' + suffix)

    digest(args.sha1, path, hashlib.sha1, 'sha1')
    digest(args.md5, path, hashlib.md5, 'md5')

def javap(args):
    """disassemble classes matching given pattern with javap"""

    parser = ArgumentParser(prog='mx javap')
    parser.add_argument('-r', '--resolve', action='store_true', help='perform eager resolution (e.g., download missing jars) of class search space')
    parser.add_argument('classes', nargs=REMAINDER, metavar='<class name patterns...>')

    args = parser.parse_args(args)

    jdk = get_jdk()
    javapExe = jdk.javap
    if not exists(javapExe):
        abort('The javap executable does not exist: ' + javapExe)
    else:
        candidates = findclass(args.classes, resolve=args.resolve, logToConsole=False)
        if len(candidates) == 0:
            log('no matches')
        selection = select_items(candidates)
        run([javapExe, '-private', '-verbose', '-classpath', classpath(resolve=args.resolve, jdk=jdk)] + selection)

### ~~~~~~~~~~~~~ commands

def suite_init_cmd(args):
    """create a suite

    usage: mx init [-h] [--repository REPOSITORY] [--subdir]
                   [--repository-kind REPOSITORY_KIND]
                   name

    positional arguments:
      name                  the name of the suite

    optional arguments:
      -h, --help            show this help message and exit
      --repository REPOSITORY
                            directory for the version control repository
      --subdir              creates the suite in a sub-directory of the repository
                            (requires --repository)
      --repository-kind REPOSITORY_KIND
                            The kind of repository to create ('hg', 'git' or
                            'none'). Defaults to 'git'
    """
    parser = ArgumentParser(prog='mx init')
    parser.add_argument('--repository', help='directory for the version control repository', default=None)
    parser.add_argument('--subdir', action='store_true', help='creates the suite in a sub-directory of the repository (requires --repository)')
    parser.add_argument('--repository-kind', help="The kind of repository to create ('hg', 'git' or 'none'). Defaults to 'git'", default='git')
    parser.add_argument('name', help='the name of the suite')
    args = parser.parse_args(args)
    if args.subdir and not args.repository:
        abort('When using --subdir, --repository needs to be specified')
    if args.repository:
        vc_dir = args.repository
    else:
        vc_dir = args.name
    if args.repository_kind != 'none':
        vc = vc_system(args.repository_kind)
        vc.init(vc_dir)
    suite_dir = vc_dir
    if args.subdir:
        suite_dir = join(suite_dir, args.name)
    suite_mx_dir = join(suite_dir, _mxDirName(args.name))
    ensure_dir_exists(suite_mx_dir)
    if os.listdir(suite_mx_dir):
        abort('{} is not empty'.format(suite_mx_dir))
    suite_py = join(suite_mx_dir, 'suite.py')
    suite_skeleton_str = """suite = {
  "name" : "NAME",
  "mxversion" : "VERSION",
  "imports" : {
    "suites": [
    ]
  },
  "libraries" : {
  },
  "projects" : {
  },
}
""".replace('NAME', args.name).replace('VERSION', str(version))
    with open(suite_py, 'w') as f:
        f.write(suite_skeleton_str)

def show_projects(args):
    """show all projects"""
    for s in suites():
        if len(s.projects) != 0:
            print(s.suite_py())
            for p in s.projects:
                print('\t' + p.name)

def show_suites(args):
    """show all suites

    usage: mx suites [-h] [--locations] [--licenses]

    optional arguments:
      -h, --help   show this help message and exit
      --locations  show element locations on disk
      --licenses   show element licenses
    """
    parser = ArgumentParser(prog='mx suites')
    parser.add_argument('-p', '--locations', action='store_true', help='show element locations on disk')
    parser.add_argument('-l', '--licenses', action='store_true', help='show element licenses')
    parser.add_argument('-a', '--archived-deps', action='store_true', help='show archived deps for distributions')
    args = parser.parse_args(args)
    def _location(e):
        if args.locations:
            if isinstance(e, Suite):
                return e.mxDir
            if isinstance(e, Library):
                return join(e.suite.dir, e.path)
            if isinstance(e, Distribution):
                return e.path
            if isinstance(e, Project):
                return e.dir
        return None
    def _show_section(name, section):
        if section:
            print('  ' + name + ':')
            for e in section:
                location = _location(e)
                out = '    ' + e.name
                data = []
                if location:
                    data.append(location)
                if args.licenses:
                    if e.theLicense:
                        l = e.theLicense.name
                    else:
                        l = '??'
                    data.append(l)
                if data:
                    out += ' (' + ', '.join(data) + ')'
                print(out)
                if name == 'distributions' and args.archived_deps:
                    for a in e.archived_deps():
                        print('      ' + a.name)

    for s in suites(True):
        location = _location(s)
        if location:
            print('{} ({})'.format(s.name, location))
        else:
            print(s.name)
        _show_section('libraries', s.libs)
        _show_section('jrelibraries', s.jreLibs)
        _show_section('jdklibraries', s.jdkLibs)
        _show_section('projects', s.projects)
        _show_section('distributions', s.dists)


_show_paths_examples = """
- `mx paths DEPENDENCY` selects the "main" product of `DEPENDENCY`
- `mx paths DEPENDENCY/*.zip` selects products of `DEPENDENCY` that match `*.zip`
- `mx paths suite:DEPENDENCY` selects `DEPENDENCY` in suite `suite`"""


def show_paths(args):
    """usage: mx paths [-h] dependency-spec

Shows on-disk path to dependencies such as libraries, distributions, etc.

positional arguments:
  dependency-spec  Dependency specification in the same format as `dependency:` sources in a layout distribution.

optional arguments:
  -h, --help       show this help message and exit
  --download       Downloads the dependency (only for libraries)."""
    parser = ArgumentParser(prog='mx paths', description="Shows on-disk path to dependencies such as libraries, distributions, etc.", epilog=_show_paths_examples, formatter_class=RawTextHelpFormatter)
    parser.add_argument('--download', action='store_true', help='Downloads the dependency (only for libraries).')
    parser.add_argument('spec', help='Dependency specification in the same format as `dependency:` sources in a layout distribution.', metavar='dependency-spec')
    args = parser.parse_args(args)
    spec = args.spec
    spec_dict = LayoutDistribution._as_source_dict('dependency:' + spec, 'NO_DIST', 'NO_DEST')
    d = dependency(spec_dict['dependency'])
    if args.download:
        if not d.isResourceLibrary() and not d.isLibrary():
            abort("--download can only be used with libraries")
        d.get_path(resolve=True)
    include = spec_dict.get('path')
    for source_file, arcname in d.getArchivableResults(single=include is None):
        if include is None or glob_match(include, arcname):
            print(source_file)


show_paths.__doc__ += '\n' + _show_paths_examples


def verify_library_urls(args):
    """verify that all suite libraries are reachable from at least one of the URLs

    usage: mx verifylibraryurls [--include-mx]
    """
    parser = ArgumentParser(prog='mx verifylibraryurls')
    parser.add_argument('--include-mx', help='', action='store_true', default=primary_suite() == _mx_suite)
    args = parser.parse_args(args)

    ok = True
    _suites = suites(True)
    if args.include_mx:
        _suites.append(_mx_suite)
    for s in _suites:
        for lib in s.libs:
            if isinstance(lib, Library) and len(lib.get_urls()) != 0 and not download(os.devnull, lib.get_urls(), verifyOnly=True, abortOnError=False, verbose=_opts.verbose):
                ok = False
                log_error('Library {} not available from {}'.format(lib.qualifiedName(), lib.get_urls()))
    if not ok:
        abort('Some libraries are not reachable')


_java_package_regex = re.compile(r"^\s*package\s+(?P<package>[a-zA-Z_][\w\.]*)\s*;$", re.MULTILINE)


### ~~~~~~~~~~~~~ CI

def suite_ci_files(suite, ci_path=None, extension=(".hocon", ".jsonnet", '.libsonnet')):
    """
    Get the list of ci files for the given suite

    :param suite: SourceSuite
    :param ci_path: str or None
    :param extension: str | tuple[str] | list[str] | set[str]
    :return:
    """
    assert isinstance(suite, SourceSuite), "suite must be a SourceSuite"
    assert extension is not None, "extension cannot be None, must be a string or iterable over strings like '.ext'."
    if isinstance(extension, str):
        extension = [extension]
    extension = set(extension)

    ci_files = os.listdir(join(suite.dir, ci_path)) if ci_path else os.listdir(suite.dir)
    return [join(ci_path, name) if ci_path else name
            for name in ci_files
            if os.path.splitext(name)[-1] in extension]


def verify_ci(args, base_suite, dest_suite, common_file=None, common_dirs=None,
              extension=(".hocon", ".jsonnet", '.libsonnet')):
    """
    Verify CI configuration

    :type args: list[str] or None
    :type base_suite: SourceSuite
    :type dest_suite: SourceSuite
    :type common_file: str | list[str] | None
    :type common_dirs: list[str] | None
    :type extension: str | tuple[str] | list[str] | set[str]
    """
    parser = ArgumentParser(prog='mx verify-ci')
    parser.add_argument('-s', '--sync', action='store_true', help='synchronize with graal configuration')
    parser.add_argument('-q', '--quiet', action='store_true', help='Only produce output if something is changed')
    args = parser.parse_args(args)

    if not isinstance(dest_suite, SourceSuite) or not isinstance(base_suite, SourceSuite):
        raise abort("Can not use verify-ci on binary suites: {0} and {1} need to be source suites".format(
            base_suite.name, dest_suite.name))

    assert extension is not None, "extension cannot be None, must be a string or iterable over strings like '.ext'."
    if isinstance(extension, str):
        extension = [extension]
    extension = set(extension)

    if isinstance(common_file, str):
        common_file = [common_file]

    common_dirs = common_dirs or []

    def _handle_error(msg, base_file, dest_file):
        if args.sync:
            log("Overriding {1} from {0}".format(os.path.normpath(base_file), os.path.normpath(dest_file)))
            shutil.copy(base_file, dest_file)
        else:
            log(msg + ": " + os.path.normpath(dest_file))
            log("Try synchronizing:")
            log("  " + base_file)
            log("  " + dest_file)
            log("Or execute 'mx verify-ci' with the  '--sync' option.")
            abort(1)

    def _common_string_end(s1, s2):
        l = 0
        while s1[l-1] == s2[l-1]:
            l -= 1
        return s1[:l]

    def _verify_file(base_file, dest_file):
        if not os.path.isfile(base_file) or not os.path.isfile(dest_file):
            _handle_error('Common CI file not found', base_file, dest_file)
        if not filecmp.cmp(base_file, dest_file):
            _handle_error('Common CI file mismatch', base_file, dest_file)
        logv("CI File '{0}' matches.".format(_common_string_end(base_file, dest_file)))

    for d in common_dirs:
        base_dir = join(base_suite.dir, d)
        dest_dir = join(dest_suite.dir, d)

        for root, _, files in os.walk(base_dir):
            rel_root = os.path.relpath(root, base_dir)
            for f in files:
                if os.path.splitext(f)[-1] in extension:
                    community_file = join(base_dir, rel_root, f)
                    enterprise_file = join(dest_dir, rel_root, f)
                    _verify_file(community_file, enterprise_file)

    if common_file:
        for f in common_file:
            base_common = join(base_suite.vc_dir, f)
            dest_common = join(dest_suite.vc_dir, f)
            _verify_file(base_common, dest_common)

    if not args.quiet:
        log("CI setup is fine.")

### ~~~~~~~~~~~~~ Java Compiler
__compile_mx_class_lock = multiprocessing.Lock()
def _compile_mx_class(javaClassNames, classpath=None, jdk=None, myDir=None, extraJavacArgs=None, as_jar=False):
    if not isinstance(javaClassNames, list):
        javaClassNames = [javaClassNames]
    myDir = join(_mx_home, 'java') if myDir is None else myDir
    binDir = join(_mx_suite.get_output_root(), 'bin' if not jdk else '.jdk' + str(jdk.version))
    javaSources = [join(myDir, n + '.java') for n in javaClassNames]
    javaClasses = [join(binDir, n + '.class') for n in javaClassNames]
    if as_jar:
        output = join(_mx_suite.get_output_root(), ('' if not jdk else 'jdk' + str(jdk.version)) + '-' + '-'.join(javaClassNames) + '.jar')
    else:
        assert len(javaClassNames) == 1, 'can only compile multiple sources when producing a jar'
        output = javaClasses[0]
    if not exists(output) or TimeStampFile(output).isOlderThan(javaSources):
        with __compile_mx_class_lock:
            ensure_dir_exists(binDir)
            javac = jdk.javac if jdk else get_jdk(tag=DEFAULT_JDK_TAG).javac
            cmd = [javac, '-d', _cygpathU2W(binDir)]
            if classpath:
                cmd.extend(['-cp', _separatedCygpathU2W(binDir + os.pathsep + classpath)])
            if extraJavacArgs:
                cmd.extend(extraJavacArgs)
            cmd += [_cygpathU2W(s) for s in javaSources]
            try:
                subprocess.check_call(cmd)
                if as_jar:
                    classfiles = []
                    for root, _, filenames in os.walk(binDir):
                        for n in filenames:
                            if n.endswith('.class'):
                                # Get top level class name
                                if '$' in n:
                                    className = n[0:n.find('$')]
                                else:
                                    className = n[:-len('.class')]
                                if className in javaClassNames:
                                    classfiles.append(os.path.relpath(join(root, n), binDir))
                    subprocess.check_call([jdk.jar, 'cfM', _cygpathU2W(output)] + classfiles, cwd=_cygpathU2W(binDir))
                logv('[created/updated ' + output + ']')
            except subprocess.CalledProcessError as e:
                abort('failed to compile ' + str(javaSources) + ' or create ' + output + ': ' + str(e))
    return myDir, output if as_jar else binDir

def _add_command_primary_option(parser):
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')

### ~~~~~~~~~~~~~ commands

def checkcopyrights(args):
    """run copyright check on the sources"""
    class CP(ArgumentParser):
        def format_help(self):
            return ArgumentParser.format_help(self) + self._get_program_help()

        def _get_program_help(self):
            help_output = _check_output_str([get_jdk().java, '-cp', classpath('com.oracle.mxtool.checkcopy'), 'com.oracle.mxtool.checkcopy.CheckCopyright', '--help'])
            return '\nother argumemnts preceded with --, e.g. mx checkcopyright --primary -- --all\n' +  help_output

    # ensure compiled form of code is up to date
    build(['--no-daemon', '--dependencies', 'com.oracle.mxtool.checkcopy'])

    parser = CP(prog='mx checkcopyrights')

    _add_command_primary_option(parser)
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    remove_doubledash(args.remainder)


    result = 0
    # copyright checking is suite specific as each suite may have different overrides
    for s in suites(True):
        if args.primary and not s.primary:
            continue
        custom_copyrights = _cygpathU2W(join(s.mxDir, 'copyrights'))
        custom_args = []
        if exists(custom_copyrights):
            custom_args = ['--custom-copyright-dir', custom_copyrights]
        rc = run([get_jdk().java, '-cp', classpath('com.oracle.mxtool.checkcopy'), 'com.oracle.mxtool.checkcopy.CheckCopyright', '--copyright-dir', _mx_home] + custom_args + args.remainder, cwd=s.dir, nonZeroIsFatal=False)
        result = result if rc == 0 else rc
    return result

### ~~~~~~~~~~~~~ Maven

def mvn_local_install(group_id, artifact_id, path, version, repo=None):
    if not exists(path):
        abort('File ' + path + ' does not exists')
    repoArgs = ['-Dmaven.repo.local=' + repo] if repo else []
    run_maven(['install:install-file', '-DgroupId=' + group_id, '-DartifactId=' + artifact_id, '-Dversion=' +
               version, '-Dpackaging=jar', '-Dfile=' + path, '-DcreateChecksum=true'] + repoArgs)

def maven_install(args):
    """install the primary suite in a local maven repository for testing"""
    parser = ArgumentParser(prog='mx maven-install')
    parser.add_argument('--no-checks', action='store_true', help='checks on status are disabled')
    parser.add_argument('--test', action='store_true', help='print info about JARs to be installed')
    parser.add_argument('--repo', action='store', help='path to local Maven repository to install to')
    parser.add_argument('--only', action='store', help='comma separated set of distributions to deploy')
    args = parser.parse_args(args)

    _mvn.check()
    s = primary_suite()
    nolocalchanges = args.no_checks or s.vc.can_push(s.vc_dir, strict=False)
    version = s.vc.parent(s.vc_dir)
    releaseVersion = s.release_version(snapshotSuffix='SNAPSHOT')
    arcdists = []
    only = []
    if args.only is not None:
        only = args.only.split(',')
    for dist in s.dists:
        # ignore non-exported dists
        if not dist.internal and not dist.name.startswith('COM_ORACLE') and hasattr(dist, 'maven') and dist.maven:
            if len(only) == 0 or dist.name in only:
                arcdists.append(dist)

    mxMetaName = _mx_binary_distribution_root(s.name)
    s.create_mx_binary_distribution_jar()
    mxMetaJar = s.mx_binary_distribution_jar_path()
    if not args.test:
        if nolocalchanges:
            mvn_local_install(_mavenGroupId(s.name), _map_to_maven_dist_name(mxMetaName), mxMetaJar, version, args.repo)
        else:
            print('Local changes found, skipping install of ' + version + ' version')
        mvn_local_install(_mavenGroupId(s.name), _map_to_maven_dist_name(mxMetaName), mxMetaJar, releaseVersion, args.repo)
        for dist in arcdists:
            if nolocalchanges:
                mvn_local_install(dist.maven_group_id(), dist.maven_artifact_id(), dist.path, version, args.repo)
            mvn_local_install(dist.maven_group_id(), dist.maven_artifact_id(), dist.path, releaseVersion, args.repo)
    else:
        print('jars to deploy manually for version: ' + version)
        print('name: ' + _map_to_maven_dist_name(mxMetaName) + ', path: ' + os.path.relpath(mxMetaJar, s.dir))
        for dist in arcdists:
            print('name: ' + dist.maven_artifact_id() + ', path: ' + os.path.relpath(dist.path, s.dir))


### ~~~~~~~~~~~~~ _private, eclipse

def _copy_eclipse_settings(p, files=None):
    processors = p.annotation_processors()

    settingsDir = join(p.dir, ".settings")
    ensure_dir_exists(settingsDir)

    for name, sources in p.eclipse_settings_sources().items():
        out = StringIO()
        print('# GENERATED -- DO NOT EDIT', file=out)
        for source in sources:
            print('# Source:', source, file=out)
            with open(source) as f:
                print(f.read(), file=out)
        if p.javaCompliance:
            jc = p.javaCompliance if p.javaCompliance.value < _max_Eclipse_JavaExecutionEnvironment else JavaCompliance(_max_Eclipse_JavaExecutionEnvironment)
            content = out.getvalue().replace('${javaCompliance}', str(jc))
        else:
            content = out.getvalue()
        if processors:
            content = content.replace('org.eclipse.jdt.core.compiler.processAnnotations=disabled', 'org.eclipse.jdt.core.compiler.processAnnotations=enabled')
        update_file(join(settingsDir, name), content)
        if files:
            files.append(join(settingsDir, name))

### ~~~~~~~~~~~~~ commands

def show_version(args):
    """print mx version"""

    parser = ArgumentParser(prog='mx version')
    parser.add_argument('--oneline', action='store_true', help='show mx revision and version in one line')
    args = parser.parse_args(args)
    if args.oneline:
        vc = VC.get_vc(_mx_home, abortOnError=False)
        if vc is None:
            print('No version control info for mx %s' % version)
        else:
            print(_sversions_rev(vc.parent(_mx_home), vc.isDirty(_mx_home), False) + ' mx %s' % version)
        return

    print(version)

@suite_context_free
def update(args):
    """update mx to the latest version"""
    parser = ArgumentParser(prog='mx update')
    parser.add_argument('-n', '--dry-run', action='store_true', help='show incoming changes without applying them')
    args = parser.parse_args(args)

    vc = VC.get_vc(_mx_home, abortOnError=False)
    if isinstance(vc, GitConfig):
        if args.dry_run:
            print(vc.incoming(_mx_home))
        else:
            print(vc.pull(_mx_home, update=True))
    else:
        print('Cannot update mx as git is unavailable')

def print_simple_help():
    print('Welcome to Mx version ' + str(version))
    print(ArgumentParser.format_help(_argParser))
    print('Modify mx.<suite>/suite.py in the top level directory of a suite to change the project structure')
    print('Here are common Mx commands:')
    print('\nBuilding and testing:')
    print(list_commands(_build_commands))
    print('Checking stylistic aspects:')
    print(list_commands(_style_check_commands))
    print('Useful utilities:')
    print(list_commands(_utilities_commands))
    print('\'mx help\' lists all commands. See \'mx help <command>\' to read about a specific command')


def list_commands(l):
    return _mx_commands.list_commands(l)

_build_commands = ['ideinit', 'build', 'unittest', 'gate', 'clean']
_style_check_commands = ['canonicalizeprojects', 'checkheaders', 'checkstyle', 'spotbugs', 'eclipseformat']
_utilities_commands = ['suites', 'envs', 'findclass', 'javap']


update_commands("mx", {
    'archive': [_archive, '[options]'],
    'benchmark' : [mx_benchmark.benchmark, '--vmargs [vmargs] --runargs [runargs] suite:benchname'],
    'benchtable': [mx_benchplot.benchtable, '[options]'],
    'benchplot': [mx_benchplot.benchplot, '[options]'],
    'binary-url': [binary_url, '<repository id> <distribution name>'],
    'build': [build, '[options]'],
    'canonicalizeprojects': [canonicalizeprojects, ''],
    'checkcopyrights': [checkcopyrights, '[options]'],
    'checkheaders': [mx_gate.checkheaders, ''],
    'checkoverlap': [checkoverlap, ''],
    'checkstyle': [checkstyle, ''],
    'clean': [clean, ''],
    'deploy-binary' : [deploy_binary, ''],
    'eclipseformat': [eclipseformat, ''],
    'eclipseinit': [eclipseinit_cli, ''],
    'envs': [show_envs, '[options]'],
    'exportlibs': [exportlibs, ''],
    'verifymultireleaseprojects' : [verifyMultiReleaseProjects, ''],
    'flattenmultireleasesources' : [flattenMultiReleaseSources, 'version'],
    'findbugs': [mx_spotbugs.spotbugs, ''],
    'spotbugs': [mx_spotbugs.spotbugs, ''],
    'findclass': [findclass, ''],
    'fsckprojects': [fsckprojects, ''],
    'gate': [mx_gate.gate, '[options]'],
    'help': [help_, '[command]'],
    'hg': [hg_command, '[options]'],
    'ideclean': [ideclean, ''],
    'ideinit': [ideinit, ''],
    'init' : [suite_init_cmd, '[options] name'],
    'jackpot': [mx_jackpot.jackpot, ''],
    'jacocoreport' : [mx_gate.jacocoreport, '[--format {html,xml}] [output directory]'],
    'java': [java_command, '[-options] class [args...]'],
    'javadoc': [javadoc, '[options]'],
    'javap': [javap, '[options] <class name patterns>'],
    'maven-deploy' : [maven_deploy, ''],
    'maven-install' : [maven_install, ''],
    'maven-url': [maven_url, '<repository id> <distribution name>'],
    'minheap' : [run_java_min_heap, ''],
    'netbeansinit': [netbeansinit, ''],
    'projectgraph': [projectgraph, ''],
    'projects': [show_projects, ''],
    'pylint': [pylint, ''],
    'sbookmarkimports': [sbookmarkimports, '[options]'],
    'scheckimports': [scheckimports, '[options]'],
    'sclone': [sclone, '[options]'],
    'scloneimports': [scloneimports, '[options]'],
    'sforceimports': [sforceimports, ''],
    'sha1': [sha1, ''],
    'sigtest': [mx_sigtest.sigtest, ''],
    'sincoming': [sincoming, ''],
    'site': [site, '[options]'],
    'sonarqube-upload': [mx_gate.sonarqube_upload, '[options]'],
    'coverage-upload': [mx_gate.coverage_upload, '[options]'],
    'spull': [spull, '[options]'],
    'stip': [stip, ''],
    'suites': [show_suites, ''],
    'paths': [show_paths, ''],
    'supdate': [supdate, ''],
    'sversions': [sversions, '[options]'],
    'testdownstream': [mx_downstream.testdownstream_cli, '[options]'],
    'update': [update, ''],
    'unstrip': [_unstrip, '[options]'],
    'urlrewrite': [mx_urlrewrites.urlrewrite_cli, 'url'],
    'verifylibraryurls': [verify_library_urls, ''],
    'verifysourceinproject': [verifysourceinproject, ''],
    'version': [show_version, ''],
})

from mx_unittest import unittest
_mx_commands.add_commands([
    unittest,
])

_argParser = ArgParser()

def _mxDirName(name):
    return 'mx.' + name

### ~~~~~~~~~~~~~ Distribution, _private

def _mx_binary_distribution_root(name):
    return name + '-mx'

def _mx_binary_distribution_jar(name):
    """the (relative) path to the location of the mx binary distribution jar"""
    return join('dists', _mx_binary_distribution_root(name) + '.jar')

def _mx_binary_distribution_version(name):
    """the (relative) path to the location of the mx binary distribution version file"""
    return join('dists', _mx_binary_distribution_root(name) + '.version')

def _install_socks_proxy_opener(proxytype, proxyaddr, proxyport=None):
    """ Install a socks proxy handler so that all urllib2 requests are routed through the socks proxy. """
    try:
        import socks
        from sockshandler import SocksiPyHandler
    except ImportError:
        warn('WARNING: Failed to load PySocks module. Try installing it with `pip install PySocks`.')
        return
    if proxytype == 4:
        proxytype = socks.SOCKS4
    elif proxytype == 5:
        proxytype = socks.SOCKS5
    else:
        abort("Unknown Socks Proxy type {0}".format(proxytype))

    opener = _urllib_request.build_opener(SocksiPyHandler(proxytype, proxyaddr, proxyport))
    _urllib_request.install_opener(opener)


def main():
    # make sure logv, logvv and warn work as early as possible
    _opts.__dict__['verbose'] = '-v' in sys.argv or '-V' in sys.argv
    _opts.__dict__['very_verbose'] = '-V' in sys.argv
    _opts.__dict__['warn'] = '--no-warning' not in sys.argv
    _opts.__dict__['quiet'] = '--quiet' in sys.argv
    global _vc_systems
    _vc_systems = [HgConfig(), GitConfig(), BinaryVC()]

    global _mx_suite
    _mx_suite = MXSuite()
    os.environ['MX_HOME'] = _mx_home

    def _get_env_upper_or_lowercase(name):
        return os.environ.get(name, os.environ.get(name.upper()))

    def _check_socks_proxy():
        """ Install a Socks Proxy Handler if the environment variable is set. """
        def _read_socks_proxy_config(proxy_raw):
            s = proxy_raw.split(':')
            if len(s) == 1:
                return s[0], None
            if len(s) == 2:
                return s[0], int(s[1])
            abort("Can not parse Socks proxy configuration: {0}".format(proxy_raw))

        def _load_socks_env():
            proxy = _get_env_upper_or_lowercase('socks5_proxy')
            if proxy:
                return proxy, 5
            proxy = _get_env_upper_or_lowercase('socks4_proxy')
            if proxy:
                return proxy, 4
            return None, -1

        # check for socks5_proxy/socks4_proxy env variable
        socksproxy, socksversion = _load_socks_env()
        if socksproxy:
            socksaddr, socksport = _read_socks_proxy_config(socksproxy)
            _install_socks_proxy_opener(socksversion, socksaddr, socksport)

    # Set the https proxy environment variable from the http proxy environment
    # variable if the former is not explicitly specified but the latter is and
    # vice versa.
    # This is for supporting servers that redirect a http URL to a https URL.
    httpProxy = os.environ.get('http_proxy', os.environ.get('HTTP_PROXY'))
    httpsProxy = os.environ.get('https_proxy', os.environ.get('HTTPS_PROXY'))
    if httpProxy:
        if not httpsProxy:
            os.environ['https_proxy'] = httpProxy
    elif httpsProxy:
        os.environ['http_proxy'] = httpsProxy
    else:
        # only check for socks proxy if no http(s) has been specified
        _check_socks_proxy()

    _argParser._parse_cmd_line(_opts, firstParse=True)

    global _mvn
    _mvn = MavenConfig()

    mx_urlrewrites.register_urlrewrites_from_env('MX_URLREWRITES')

    _mx_suite._init_metadata()
    _mx_suite._resolve_dependencies()
    _mx_suite._post_init()

    # Do not treat initial_command as an abbreviation as it would prevent
    # mx extensions from defining commands that match an abbreviation.
    initial_command = _argParser.initialCommandAndArgs[0] if len(_argParser.initialCommandAndArgs) > 0 else None
    is_suite_context_free = initial_command and initial_command in _suite_context_free
    should_discover_suites = not is_suite_context_free and not (initial_command and initial_command in _no_suite_discovery)
    should_load_suites = should_discover_suites and not (initial_command and initial_command in _no_suite_loading)
    is_optional_suite_context = not initial_command or initial_command in _optional_suite_context

    assert not should_load_suites or should_discover_suites, initial_command

    def _setup_binary_suites():
        global _binary_suites
        bs = os.environ.get('MX_BINARY_SUITES')
        if bs is not None:
            if len(bs) > 0:
                _binary_suites = bs.split(',')
            else:
                _binary_suites = []

    SourceSuite._load_env_file(join(dot_mx_dir(), 'env'))
    primarySuiteMxDir = None
    if is_suite_context_free:
        _setup_binary_suites()
        commandAndArgs = _argParser._parse_cmd_line(_opts, firstParse=False)
    else:
        primarySuiteMxDir = _findPrimarySuiteMxDir()
        if primarySuiteMxDir == _mx_suite.mxDir:
            _primary_suite_init(_mx_suite)
            _mx_suite.internal = False
            mx_benchmark.init_benchmark_suites()
        elif primarySuiteMxDir:
            # We explicitly load the 'env' file of the primary suite now as it might
            # influence the suite loading logic.  During loading of the sub-suites their
            # environment variable definitions are collected and will be placed into the
            # os.environ all at once.  This ensures that a consistent set of definitions
            # are seen.  The primary suite must have everything required for loading
            # defined.
            SourceSuite._load_env_in_mxDir(primarySuiteMxDir)
            additional_env = _opts.additional_env or get_env('MX_ENV_PATH')
            if additional_env:
                SourceSuite._load_env_in_mxDir(primarySuiteMxDir, file_name=additional_env, abort_if_missing=True)

            _setup_binary_suites()
            if should_discover_suites:
                primary = _discover_suites(primarySuiteMxDir, load=should_load_suites)
            else:
                primary = SourceSuite(primarySuiteMxDir, load=False, primary=True)
            _primary_suite_init(primary)
        else:
            if not is_optional_suite_context:
                abort('no primary suite found for %s' % initial_command)

        for envVar in _loadedEnv:
            value = _loadedEnv[envVar]
            if os.environ.get(envVar) != value:
                logv('Setting environment variable %s=%s' % (envVar, value))
                os.environ[envVar] = value

        commandAndArgs = _argParser._parse_cmd_line(_opts, firstParse=False)

    if _opts.java_home:
        logv('Setting environment variable %s=%s from --java-home' % ('JAVA_HOME', _opts.java_home))
        os.environ['JAVA_HOME'] = _opts.java_home

    if _opts.mx_tests:
        MXTestsSuite()

    if primarySuiteMxDir and not _mx_suite.primary and should_load_suites:
        primary_suite().recursive_post_init()
        _check_dependency_cycles()

    if len(commandAndArgs) == 0:
        print_simple_help()
        return

    # add JMH archive participants
    def _has_jmh_dep(dist):
        class NonLocal:
            """ Work around nonlocal access """
            jmh_found = False

        def _visit_and_find_jmh_dep(dst, edge):
            if NonLocal.jmh_found:
                return False
            if dst.isLibrary() and dst.name.startswith('JMH'):
                NonLocal.jmh_found = True
                return False
            return True

        dist.walk_deps(preVisit=_visit_and_find_jmh_dep)
        return NonLocal.jmh_found

    for s_ in suites(True, includeBinary=False):
        for d in s_.dists:
            if _has_jmh_dep(d):
                d.set_archiveparticipant(JMHArchiveParticipant(d))

    command = commandAndArgs[0]
    mx_gate._mx_command_and_args = commandAndArgs
    mx_gate._mx_args = sys.argv[1:sys.argv.index(command)]
    command_args = commandAndArgs[1:]

    if command not in _mx_commands.commands():
        hits = [c for c in _mx_commands.commands().keys() if c.startswith(command)]
        if len(hits) == 1:
            command = hits[0]
        elif len(hits) == 0:
            abort('mx: unknown command \'{0}\'\n{1}use "mx help" for more options'.format(command, _format_commands()))
        else:
            abort('mx: command \'{0}\' is ambiguous\n    {1}'.format(command, ' '.join(hits)))

    c = _mx_commands.commands()[command]

    if primarySuiteMxDir and should_load_suites:
        if not _mx_commands.get_command_property(command, "keepUnsatisfiedDependencies"):
            global _removedDeps
            _removedDeps = _remove_unsatisfied_deps()

    # Finally post_init remaining distributions
    for s_ in suites(includeBinary=False, include_mx=True):
        for d in s_.dists:
            d.post_init()

    def term_handler(signum, frame):
        abort(1, killsig=signal.SIGTERM)
    signal.signal(signal.SIGTERM, term_handler)

    def quit_handler(signum, frame):
        _send_sigquit()
    if not is_windows():
        signal.signal(signal.SIGQUIT, quit_handler)

    try:
        if _opts.timeout != 0:
            def alarm_handler(signum, frame):
                abort('Command timed out after ' + str(_opts.timeout) + ' seconds: ' + ' '.join(commandAndArgs))
            signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(_opts.timeout)
        retcode = c(command_args)
        if retcode is not None and retcode != 0:
            abort(retcode)
    except KeyboardInterrupt:
        # no need to show the stack trace when the user presses CTRL-C
        abort(1, killsig=signal.SIGINT)


# The comment after VersionSpec should be changed in a random manner for every bump to force merge conflicts!
version = VersionSpec("5.225.2")  # GR-16861 - update CI to jvmci-19.2-b01

currentUmask = None
_mx_start_datetime = datetime.utcnow()

if __name__ == '__main__':
    # Capture the current umask since there's no way to query it without mutating it.
    currentUmask = os.umask(0)
    os.umask(currentUmask)

    main()
