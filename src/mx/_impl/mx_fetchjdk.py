#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2022, Oracle and/or its affiliates. All rights reserved.
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

__all__ = [
    "fetch_jdk_cli",
    "fetch_jdk",
    "PathList",
]

import os, shutil, json, re, glob
from os.path import join, exists, abspath, dirname, basename, isabs
from argparse import ArgumentParser

try:
    from urllib import quote
except ImportError:
    from urllib.parse import quote

from .mx import suite_context_free, _mx_home, command, atomic_file_move_with_fallback, is_quiet
from .select_jdk import get_setvar_format
from . import mx, mx_urlrewrites


@command('mx', 'fetch-jdk', '[options]')
@suite_context_free
def fetch_jdk_cli(args):
    """fetches required JDK version

    If mx is not passed the --quiet flag, menu will be printed for available JDK selection.
    """
    fetch_jdk(args)


def fetch_jdk(args):
    """
    Installs a JDK based on the coordinates in `args`. See ``mx fetch-jdk --help`` for more info.
    Note that if a JDK already exists at the installation location denoted by `args`, no action is taken.

    :return str: the JAVA_HOME for the JDK at the installation location denoted by `args`
    """
    settings = _parse_args(args)

    jdk_binary = settings["jdk-binary"]
    jdks_dir = settings["jdks-dir"]
    artifact = jdk_binary._folder_name
    final_path = jdk_binary.get_final_path(jdks_dir)
    urls = [mx_urlrewrites.rewriteurl(url) for url in jdk_binary._urls]
    if not is_quiet():
        if not mx.ask_yes_no(f"Install {artifact} to {final_path}", default='y'):
            mx.abort("JDK installation canceled")
    if not settings["force"] and exists(final_path):
        if settings["keep-archive"]:
            mx.warn("The --keep-archive option is ignored when the JDK is already installed.")
        mx.log(f"Requested JDK is already installed at {final_path}")
    else:
        if settings["force"] and exists(final_path):
            mx.rmtree(final_path)
        # Try to extract on the same file system as the target to be able to atomically move the result.
        with mx.TempDir(parent_dir=jdks_dir) as temp_dir:
            part = 1
            jdk_root_folder = None
            extracted_path = join(temp_dir, 'extracted')
            for url in urls:
                fraction = '' if len(urls) == 1 else f' (part {part} of {len(urls)})'
                sha_url = url + ".sha1"
                archive_name = url[url.rfind('/') + 1:]

                archive_target_location = join(jdks_dir, archive_name)

                mx.log(f"Fetching {artifact} archive{fraction} from {url}...")
                archive_location = join(temp_dir, archive_name)
                mx._opts.no_download_progress = is_quiet()
                try:
                    digest = mx._hashFromUrl(sha_url)
                except Exception as e: #pylint: disable=broad-except
                    mx.abort(f'Error retrieving {sha_url}: {e}')

                mx.download_file_with_digest(artifact, archive_location, [url], digest, resolve=True, mustExist=True, sources=False)
                untar = mx.TarExtractor(archive_location)

                mx.log(f"Installing {artifact}{fraction} to {final_path}...")

                try:
                    untar.extract(extracted_path)
                except:
                    mx.rmtree(temp_dir, ignore_errors=True)
                    mx.abort("Error parsing archive. Please try again")

                if part == 1:
                    jdk_root_folder = _get_extracted_jdk_archive_root_folder(extracted_path)
                if settings["keep-archive"]:
                    atomic_file_move_with_fallback(archive_location, archive_target_location)
                    atomic_file_move_with_fallback(archive_location + '.sha1', archive_target_location + ".sha1")
                    mx.log(f"Archive is located at {archive_target_location}")
                part += 1

            atomic_file_move_with_fallback(join(extracted_path, jdk_root_folder), final_path)

    curr_path = final_path
    if exists(join(final_path, 'Contents', 'Home')):
        if settings["strip-contents-home"]:
            with mx.TempDir() as tmp_path:
                tmp_jdk = join(tmp_path, 'jdk')
                shutil.move(final_path, tmp_jdk)
                shutil.move(join(tmp_jdk, 'Contents', 'Home'), final_path)
        else:
            final_path = join(final_path, 'Contents', 'Home')

    alias = settings.get('alias')
    if alias:
        alias_full_path = join(jdks_dir, alias)
        if not exists(alias_full_path) or os.path.realpath(alias_full_path) != os.path.realpath(abspath(curr_path)):
            if os.path.islink(alias_full_path):
                os.unlink(alias_full_path)
            elif exists(alias_full_path):
                mx.abort(alias_full_path + ' exists and it is not an existing symlink so it can not be used for a new symlink. Please remove it manually.')

            if mx.can_symlink():
                if isabs(alias):
                    os.symlink(curr_path, alias_full_path)
                else:
                    reldir = os.path.relpath(dirname(curr_path), dirname(alias_full_path))
                    if reldir == '.':
                        alias_target = basename(curr_path)
                    else:
                        alias_target = join(reldir, basename(curr_path))
                    os.symlink(alias_target, alias_full_path)
            else:
                mx.copytree(curr_path, alias_full_path)
            final_path = alias_full_path

    mx.log("Run the following to set JAVA_HOME in your shell:")
    shell = os.environ.get("SHELL")
    if shell is None:
        shell = ''
    if not settings["strip-contents-home"] and exists(join(final_path, 'Contents', 'Home')):
        java_home = join(final_path, 'Contents', 'Home')
    else:
        java_home = final_path
    mx.log(get_setvar_format(shell) % ("JAVA_HOME", abspath(java_home)))
    return final_path


def _find_file(start, filename):
    """
    Searches up the directory hierarchy starting at `start` for a file named `filename`
    and returns the first one found or None if no match is found. The searched locations
    for each directory ``dir`` are:
        dir/<filename>
        dir/.ci/<filename>
        dir/ci/<filename>
        dir/.git/*/<filename>
        dir/.hg/*/<filename>
    """
    probe_dir = start
    path = join(probe_dir, filename)
    while not exists(path):
        probe_dir_parent = dirname(probe_dir)

        candidates = [join(probe_dir, '.ci', filename), join(probe_dir, 'ci', filename)] + \
            glob.glob(join(probe_dir, '.git', '*', filename)) + \
            glob.glob(join(probe_dir, '.hg', '*', filename))

        for path in candidates:
            if exists(path):
                return path

        next_probe_dir = probe_dir_parent
        if not next_probe_dir or next_probe_dir == probe_dir:
            break
        probe_dir = next_probe_dir
        path = join(probe_dir, filename)
    if not exists(path):
        return None
    return path


def _check_exists_or_None(path):
    if path is not None and not exists(path):
        mx.abort("File doesn't exist: " + path)
    return path


class PathList(object):
    def __init__(self):
        self.paths = []

    def add(self, path):
        if path is not None and exists(path) and path not in self.paths:
            self.paths.append(path)

    def __repr__(self):
        return os.pathsep.join(self.paths)


def _parse_args(args):
    """
    Defines and parses the command line arguments in `args` for the ``fetch-jdk`` command.

    :return dict: a dictionary configuring the action to be taken by ``fetch-jdk``. The entries are:
                "keep-archive": True if the downloaded archive is to be retained after extraction, False if it is to be deleted
                "jdks-dir": directory in which archive is to be extracted
                "jdk-binary": a _JdkBinary object
                "alias": path of a symlink to create to the extracted JDK
                "strip-contents-home": True if the ``Contents/Home`` should be stripped if it exists from the extracted JDK
    """
    settings = {}
    settings["keep-archive"] = False
    settings["jdks-dir"] = join(mx.dot_mx_dir(), 'jdks')

    # Order in which to look for common.json:
    # 1. Primary suite path (i.e. -p mx option)
    # 2. Current working directory
    # 4. $MX_HOME/common.json
    path_list = PathList()
    if mx._primary_suite_path:
        path_list.add(_find_file(mx._primary_suite_path, 'common.json'))
    path_list.add(_find_file(os.getcwd(), 'common.json'))
    path_list.add(join(_mx_home, 'common.json'))
    default_jdk_defs_location = path_list.paths[0]

    # Order in which to look for jdk-binaries.json:
    # 1. Primary suite path (i.e. -p mx option)
    # 2. Current working directory
    # 4. $MX_HOME/jdk-binaries.json
    path_list = PathList()
    if mx._primary_suite_path:
        path_list.add(_find_file(mx._primary_suite_path, 'jdk-binaries.json'))
    path_list.add(_find_file(os.getcwd(), 'jdk-binaries.json'))
    path_list.add(join(_mx_home, 'jdk-binaries.json'))
    default_jdk_binaries_location = str(path_list)

    parser = ArgumentParser(prog='mx fetch-jdk', usage='%(prog)s [options] [<jdk-id>]' + r"""
        Download and install JDKs.

        The set of JDKS available for download are specified by the "jdks" field of the JSON
        object loaded by --configuration. The "jdks" field is itself is an object whose field names
        are JDK identifiers and whose values are objects that must include "version". The JDK object
        fields "build_id" and "extrabundles" are also specially handled. For example:

        {
          "jdks": {
            "openjdk8":           {"version": "8u302+02-jvmci-21.2-b02" },
            "labsjdk-ce-11":      {"version": "ce-11.0.11+8-jvmci-21.2-b02" },
            "labsjdk-ce-20":      {"version": "ce-20+24-jvmci-23.0-b02" },
            "oraclejdk21":        {"version": "21", "build_id": "14", "extrabundles": ["static-libs"] },
          }
        }

        The location of binaries matching these JDK definitions is specified by the "jdk-binaries" field
        of the JSON object loaded by --jdk-binaries (can be the same value as --configuration). For
        example:

        {
          "jdk-binaries": {
            "openjdk8": {
              "filename": "openjdk-{version}-{platform}",
              "url": "https://github.com/graalvm/graal-jvmci-8/releases/download/{version|jvmci}/{filename}.tar.gz"
            },
            "labsjdk-ce-(P?<major>\\d+)": {
              "filename": "labsjdk-{version}-{platform}",
              "url": "https://github.com/graalvm/labs-openjdk-{major}/releases/download/{version|jvmci}/{filename}.tar.gz"
            }
          }
        }

        The "jdk-binaries.<id>" object specifies the URLs that compose to form a JDK binary for the "jdks.<id>" object.
        The "filename" and "url" attributes of a JDK binary object are template strings with curly braces denoting
        keywords that will be replaced with their values. The supported keywords and their value for a
        "jdk-binaries.<id>" object are:

        version      The value of "jdks.<id>.version".
        build_id     The value of "jdks.<id>.build_id".
        bundle       Value derived from "jdks.<id>.extrabundles". For example, if "extrabundles" is ["static-libs"],
                     this keyword will have the values ["", "-static-libs"]. 
        platform     The value denoting the operating system and architecture (e.g. "linux-amd64").
        platform_jdk Same as platform except using JDK naming ("darwin" -> "macos", "amd64" -> "x64").
        filename     The value of "jdk-binaries.<id>.filename".

        Each keyword value can be processed by a filter by appending "|<filter>" to the keyword selector.
        The supported filters are:

        jvmci        Extracts the first string that looks like a jvmci version.
                     Note that with JDK 21, the JVMCI version scheme changed. There are no more JVMCI major and minor versions.
                     Instead, the full JDK version is considered part of the JVMCI version, e.g. "22.0.1+3-jvmci-b01".
                     In that case, the {jvmci} keyword will return the same as the {jvmci-tag} keyword. Examples:
                       "8u302+05-jvmci-21.2-b01" -> "21.2-b01"
                       "prefix-22.0.1+3-jvmci-b01Suffix" -> "22.0.1+3-jvmci-b01"

        jvmci-tag    Extracts the first string that looks like a jvmci tag. Examples:
                       "8u302+05-jvmci-21.2-b01" -> "jvmci-21.2-b01"
                       "prefix-22.0.1+3-jvmci-b01Suffix" -> "22.0.1+3-jvmci-b01"

        If jdk-binaries.<id> contains "(P?<" it will be interpreted as a regular expression and the named pattern(s)
        will be additional keywords for the template string (e.g. "major" in the example above).
        
        If a template string uses a keyword whose value is a list, there will be one instantiated string
        per unique entry in the list. 
    """)

    jdk_id_group = parser.add_mutually_exclusive_group()
    jdk_id_group.add_argument('jdk_id_pos', action='store', metavar='<jdk-id>', nargs='?', help='see --jdk-id')
    jdk_id_group.add_argument('--jdk-id', '--java-distribution', action='store', metavar='<id>', help='Identifier of the JDK that should be downloaded (e.g., "labsjdk-ce-11" or "openjdk8")')
    parser.add_argument('--configuration', action='store', metavar='<path>', help=f'location of JSON file containing JDK definitions (default: {default_jdk_defs_location})')
    parser.add_argument('--jdk-binaries', action='store', metavar='<path>', help=f'{os.pathsep} separated JSON files specifying location of JDK binaries (default: {default_jdk_binaries_location})')
    parser.add_argument('--to', action='store', metavar='<dir>', help=f"location where JDK will be installed. Specify <system> to use the system default location. (default: {settings['jdks-dir']})")
    alias_group = parser.add_mutually_exclusive_group()
    alias_group.add_argument('--alias', action='store', metavar='<path>', help='name under which the extracted JDK should be made available (e.g. via a symlink). A relative path will be resolved against the value of the --to option.')
    alias_group.add_argument('--auto-alias', '-A', action='store_const', dest='alias', const='-', help='make the extracted JDK available via its name (e.g. via a symlink). The path will be resolved against the value of the --to option.')
    parser.add_argument('--arch', action='store', metavar='<name>', help=f'arch of binary to be retrieved (default: {mx.get_arch()})', default=mx.get_arch())
    parser.add_argument('--keep-archive', action='store_true', help='keep downloaded JDK archive')
    parser.add_argument('--strip-contents-home', action='store_true', help='strip Contents/Home if it exists from installed JDK')
    parser.add_argument('--list', action='store_true', help='list the available JDKs and exit')
    parser.add_argument('--force', action='store_true', help='force download the JDK and overwrite existing files')
    args = parser.parse_args(args)

    if args.to is not None:
        if args.to == '<system>':
            args.to = _default_system_jdks_dir()
        settings["jdks-dir"] = args.to
    elif args.arch != mx.get_arch():
        settings["jdks-dir"] = join(settings["jdks-dir"], args.arch)

    if not _check_write_access(settings["jdks-dir"]):
        mx.abort(f"JDK installation directory {settings['jdks-dir']} is not writeable." + os.linesep +
                 "Either re-run with elevated privileges (e.g. sudo) or specify a writeable directory with the --to option.")

    jdk_defs_location = _check_exists_or_None(args.configuration) or default_jdk_defs_location
    jdk_binaries_locations = (args.jdk_binaries or default_jdk_binaries_location).split(os.pathsep)

    jdk_defs = _parse_jdk_defs(jdk_defs_location)
    jdk_binaries = _parse_jdk_binaries(jdk_binaries_locations, jdk_defs, args.arch)

    if args.list:
        for jdk in sorted(jdk_defs.keys()):
            mx.log(jdk)
        # cannot use mx.abort as it always adds a newline
        raise SystemExit(0)

    # use positional or option argument
    jdk_id = args.jdk_id_pos or args.jdk_id
    if jdk_id is not None:
        settings["jdk-binary"] = _get_jdk_binary_or_abort(jdk_binaries, jdk_id)
    else:
        if is_quiet():
            parser.print_usage()
            mx.abort('A <jdk-id> must be provided in quiet mode.')
        settings["jdk-binary"] = _choose_jdk_binary(jdk_binaries)

    if args.alias is not None:
        if args.alias == "-":
            settings["alias"] = settings["jdk-binary"]._jdk_id
        else:
            settings["alias"] = args.alias

    if args.keep_archive is not None:
        settings["keep-archive"] = args.keep_archive

    settings["strip-contents-home"] = args.strip_contents_home
    settings["force"] = args.force

    return settings


def _get_jdk_binary_or_abort(jdk_binaries, jdk_id):
    jdk_binary = jdk_binaries.get(jdk_id)
    if not jdk_binary:
        mx.abort(f"Unknown JDK identifier: {jdk_id} [Known JDKs: {', '.join(jdk_binaries.keys())}]")
    return jdk_binary


def _parse_json(path):
    with open(path) as fp:
        try:
            return json.load(fp)
        except ValueError as e:
            mx.abort(f'The file ({path}) does not contain legal JSON: {e}')


def _get_json_attr(json_object, name, expect_type, source, optional=False):
    value = json_object.get(name) or mx.abort(f'{source}: missing "{name}" attribute')
    if not isinstance(value, expect_type):
        mx.abort(f'{source} -> "{name}": value ({value}) must be a {expect_type.__name__}, not a {value.__class__.__name__}')
    return value


def _check_jdk_def(jdk_def, jdk_id, path):
    _get_json_attr(jdk_def, 'version', str, f'{path} -> "jdks" -> "{jdk_id}"')
    return jdk_def


def _parse_jdk_defs(path):
    obj = _parse_json(path)
    return {jdk_id: _check_jdk_def(jdk_def, jdk_id, path)
            for jdk_id, jdk_def in _get_json_attr(obj, 'jdks', dict, path).items()}


def _parse_jdk_binaries(paths, jdk_defs, arch):
    jdk_binaries = {}
    for path in paths:
        if not exists(path):
            mx.abort("File doesn't exist: " + path)

        obj = _parse_json(path)

        for qualified_jdk_id, config in _get_json_attr(obj, 'jdk-binaries', dict, path).items():
            source = f'{path} -> "jdk-binaries" -> "{qualified_jdk_id}"'

            def get_entry(name):
                value = config.get(name) or mx.abort(f'{source}: missing "{name}" attribute')
                if not isinstance(value, str):
                    mx.abort(f'{source} -> "{name}": value ({value}) must be a {str.__name__}, not a {value.__class__.__name__}')
                return value

            jdk_id_pattern, qualifier = qualified_jdk_id.split(':', 1) if ':' in qualified_jdk_id else (qualified_jdk_id, '')

            for jdk_id, jdk_def, keywords in _matching_jdk_defs(jdk_defs, jdk_id_pattern):
                if jdk_def:
                    jdk_binary_id = jdk_id + qualifier
                    if jdk_binary_id not in jdk_binaries:
                        jdk_binary = _JdkBinary(jdk_binary_id, jdk_def, get_entry('filename'), get_entry('url'), source, arch, keywords)
                        jdk_binaries[jdk_binary_id] = jdk_binary
    return jdk_binaries


def _matching_jdk_defs(jdk_defs, jdk_id_selector):
    """
    Finds entries in `jdk_defs` whose name matches `jdk_id_selector`.

    :return: a generator of tuples with jdk_id, jdk_def, keywords
    """
    if '(?P<' in jdk_id_selector:
        jdk_id_re = re.compile(jdk_id_selector)
        for jdk_id, jdk_def in jdk_defs.items():
            m = jdk_id_re.fullmatch(jdk_id)
            if m:
                yield jdk_id, jdk_def, m.groupdict()
    yield jdk_id_selector, jdk_defs.get(jdk_id_selector), {}


def _default_system_jdks_dir():
    locations = {
        "darwin": '/Library/Java/JavaVirtualMachines',
        "linux": '/usr/lib/jvm',
        "solaris": '/usr/jdk/instances',
        "windows": r'C:\Program Files\Java'
    }
    return locations[mx.get_os()]


def _check_write_access(path):
    try:
        if not exists(path):
            os.makedirs(path)
        if not os.access(path, os.W_OK):
            raise IOError
        return True
    except (IOError, OSError):
        return False


def _get_extracted_jdk_archive_root_folder(extracted_archive_path):
    root_folders = os.listdir(extracted_archive_path)
    if len(root_folders) != 1:
        mx.abort("JDK archive layout changed. Please contact the mx maintainers.")
    return root_folders[0]


def _choose_jdk_binary(jdk_binaries):
    index = 1
    choices = sorted(jdk_binaries.items())
    for jdk_id, jdk_binary in choices:
        prefix = f'[{index}]'

        print(f"{prefix:5} {jdk_id.ljust(25)} | {jdk_binary.selector()}")
        index += 1
    print(f"{f'[{index}]':5} Other version")
    while True:
        try:
            try:
                choice = input("Select JDK> ")
            except SyntaxError:  # Empty line
                choice = ""

            if choice == "":
                raise IndexError('<empty>')
            try:
                index = int(choice) - 1
            except ValueError:
                raise IndexError(choice)

            if index < 0:
                raise IndexError(choice)
            if index == len(choices):
                choice = input(f"Select base JDK (1 .. {index})> ")
                base_index = int(choice) - 1
                if base_index < 0 or base_index >= index:
                    raise IndexError(choice)
                base_jdk = choices[base_index][1]
                selector = input(f"Enter selector [{base_jdk.selector()}]> ")
                if selector == "":
                    selector = base_jdk.selector()
                return base_jdk.with_selector(selector)
            return choices[index][1]
        except (NameError, IndexError) as e:
            mx.warn(f"Invalid selection: {e}")
        except EOFError:
            mx.abort(1)


class _JdkBinary(object):

    def __init__(self, jdk_id, jdk_def, filename, url, source, arch, keywords):
        version = jdk_def["version"]
        build_id = jdk_def.get("build_id")
        self._jdk_id = jdk_id
        self._jdk_def = jdk_def
        self._filename_template = filename
        self._url_template = url
        self._source = source
        self._arch = arch
        self._original_keywords = dict(keywords)
        platform = mx.get_os() + '-' + arch
        keywords.setdefault('version', version)
        keywords.setdefault('platform', platform)
        keywords.setdefault('platform_jdk', platform.replace("amd64", "x64").replace("darwin", "macos"))
        extrabundles = jdk_def.get('extrabundles')
        if extrabundles is not None:
            if not isinstance(extrabundles, list):
                mx.abort(f'{source}: JDK definition of "extrabundles" is not a list')
            keywords.setdefault('bundle', [''] + [f'-{eb}' for eb in extrabundles])
        if build_id: keywords.setdefault('build_id', build_id)
        self._filenames = _instantiate(filename, keywords, source, jdk_def)
        keywords['filename'] = self._filenames
        version_suffix = _instantiate('{version|jvmci-tag}', keywords, source, jdk_def)[0]
        self._folder_name = f"{jdk_id}-{version_suffix}"
        if build_id: self._folder_name += '+' + build_id
        self._urls = _instantiate(url, {k: _quote(v) for k, v in keywords.items()}, source, jdk_def)

    def __repr__(self):
        return f'{self._jdk_id}: files={self._filenames}, urls={self._urls}'

    SELECTOR_EXTRA_ATTRS = ("build_id",)
    def selector(self):
        s = f'{self._jdk_def["version"]}'
        for a in _JdkBinary.SELECTOR_EXTRA_ATTRS:
            if a in self._jdk_def:
                s = f'{s} {a}={self._jdk_def[a]}'
        return s

    def with_selector(self, selector):
        jdk_def = dict(self._jdk_def)
        parts = selector.split()
        version = parts[0]
        jdk_def["version"] = version
        if len(parts) > 1:
            for p in parts[1:]:
                assign = p.split('=', 1)
                if len(assign) != 2:
                    mx.abort(f"Extra selector not of format <name>=<value>: {p}")
                name, value = assign
                if name not in _JdkBinary.SELECTOR_EXTRA_ATTRS:
                    mx.abort(f'Unknown extra selector "{name}"')
                jdk_def[name] = value
        keywords = self._original_keywords
        return _JdkBinary(self._jdk_id, jdk_def, self._filename_template, self._url_template, self._source, self._arch, keywords)

    def get_final_path(self, jdk_path):
        return join(jdk_path, self._folder_name)


_instantiate_filters = {
    'jvmci': lambda value: re.sub(r"(?:.*)-(.*-jvmci-b\d+).*|.*jvmci-(\d+\.\d+-b\d+).*", r"\1\2", value),
    'jvmci-tag': lambda value: re.sub(r"(?:.*)-(.*-jvmci-b\d+).*|.*(jvmci-\d+\.\d+-b\d+).*", r"\1\2", value)
}

def _quote(value):
    if isinstance(value, list):
        return [quote(v) for v in value]
    return quote(value)

def _merge_dicts(d1, d2):
    # `d | other` only supported as of Python 3.9
    res = dict(d1)
    res.update(d2)
    return res

def _instantiate(template, keywords, source, jdk_def):
    flattened_keywords = [{}]
    for name, values in keywords.items():
        if not isinstance(values, list):
            values = [values]
        lists = []
        for value in values:
            lists.append([_merge_dicts(m, {name: value}) for m in flattened_keywords])
        flattened_keywords = [item for sublist in lists for item in sublist]

    instantiations = []
    for keywords_dict in flattened_keywords:
        def repl(match):
            parts = match.group(1).split('|')
            keyword = parts[0]
            if keyword not in keywords_dict:
                supported_keywords = '", "'.join(sorted(keywords_dict.keys()))
                mx.abort(f'{source}: Error instantiating "{template}": "{keyword}" is an unrecognized keyword.\nSupported keywords: "{supported_keywords}"')
            filters = parts[1:]
            instantiation = keywords_dict[keyword]
            for f in filters:
                func = _instantiate_filters.get(f)
                if not func:
                    supported_filters = '", "'.join(sorted(_instantiate_filters.keys()))
                    mx.abort(f'{source}: Error instantiating "{template}": "{f}" is an unrecognized filter.\nSupported filters: "{supported_filters}"')
                instantiation = func(instantiation)
            return instantiation

        instantiation = re.sub(r'{([^}]+)}', repl, template)
        if instantiation not in instantiations:
            instantiations.append(instantiation)
    return instantiations
