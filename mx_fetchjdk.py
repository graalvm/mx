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
from __future__ import print_function
import os, shutil, json, re
from os.path import join, exists, abspath, dirname
from argparse import ArgumentParser

from mx import suite_context_free, _mx_home, command, atomic_file_move_with_fallback, is_quiet
from select_jdk import get_setvar_format
import mx, mx_urlrewrites

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
    base_path = settings["base-path"]
    artifact = jdk_binary.get_folder_name()
    final_path = jdk_binary.get_final_path(base_path)
    url = mx_urlrewrites.rewriteurl(jdk_binary._url)
    sha_url = url + ".sha1"
    archive_name = jdk_binary._archive
    archive_target_location = join(base_path, archive_name)

    if not is_quiet():
        if not mx.ask_yes_no("Install {} to {}".format(artifact, final_path), default='y'):
            mx.abort("JDK installation canceled")

    if exists(final_path):
        if settings["keep-archive"]:
            mx.warn("The --keep-archive option is ignored when the JDK is already installed.")
        mx.log("Requested JDK is already installed at {}".format(final_path))
    else:
        # Try to extract on the same file system as the target to be able to atomically move the result.
        with mx.TempDir(parent_dir=base_path) as temp_dir:
            mx.log("Fetching {} archive from {}...".format(artifact, url))
            archive_location = join(temp_dir, archive_name)
            mx._opts.no_download_progress = is_quiet()
            try:
                sha1_hash = mx._hashFromUrl(sha_url).decode('utf-8')
            except Exception as e: #pylint: disable=broad-except
                mx.abort('Error retrieving {}: {}'.format(sha_url, e))

            mx.download_file_with_sha1(artifact, archive_location, [url], sha1_hash, archive_location + '.sha1', resolve=True, mustExist=True, sources=False)
            untar = mx.TarExtractor(archive_location)

            mx.log("Installing {} to {}...".format(artifact, final_path))

            extracted_path = join(temp_dir, 'extracted')
            try:
                untar.extract(extracted_path)
            except:
                mx.rmtree(temp_dir, ignore_errors=True)
                mx.abort("Error parsing archive. Please try again")

            jdk_root_folder = _get_extracted_jdk_archive_root_folder(extracted_path)
            if settings["keep-archive"]:
                atomic_file_move_with_fallback(archive_location, archive_target_location)
                atomic_file_move_with_fallback(archive_location + '.sha1', archive_target_location + ".sha1")
                mx.log("Archive is located at {}".format(archive_target_location))

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

    if "alias" in settings:
        alias_full_path = join(base_path, settings["alias"])
        if os.path.islink(alias_full_path):
            os.unlink(alias_full_path)
        elif exists(alias_full_path):
            mx.abort(alias_full_path + ' exists and it is not an existing symlink so it can not be used for a new symlink. Please remove it manually.')

        if not (mx.is_windows() or mx.is_cygwin()):
            os.symlink(abspath(curr_path), alias_full_path)
        else:
            mx.copytree(curr_path, alias_full_path, symlinks=True) # fallback for windows
        final_path = alias_full_path


    mx.log("Run the following to set JAVA_HOME in your shell:")
    shell = os.environ.get("SHELL")
    if shell is None:
        shell = ''
    mx.log(get_setvar_format(shell) % ("JAVA_HOME", abspath(final_path)))
    return final_path

def _find_file(start, filename):
    """
    Searches up the directory hierarchy starting at `start` for a file named `filename`
    and returns the first one found or None if no match is found.
    """
    probe_dir = start
    path = join(probe_dir, filename)
    while not exists(path):
        next_probe_dir = dirname(probe_dir)
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
                "base-path": directory in which archive is to be extracted
                "jdk-binary": a _JdkBinary object
                "alias": path of a symlink to create to the extracted JDK
                "strip-contents-home": True if the ``Contents/Home`` should be stripped if it exists from the extracted JDK
    """
    settings = {}
    settings["keep-archive"] = False
    settings["base-path"] = _default_base_path()

    # Order in which to look for common.json:
    # 1. Primary suite path (i.e. -p mx option)
    # 2. Current working directory
    # 4. $MX_HOME/common.json
    path_list = PathList()
    if mx._primary_suite_path:
        path_list.add(_find_file(mx._primary_suite_path, 'common.json'))
    path_list.add(_find_file(os.getcwd(), 'common.json'))
    path_list.add(join(_mx_home, 'common.json'))
    default_jdk_versions_location = path_list.paths[0]

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

    parser = ArgumentParser(prog='mx fetch-jdk', usage='%(prog)s [options]' + """
        Download and install JDKs.

        The set of JDKS available for download are specified by the "jdks" field of the JSON
        object loaded by --configuration. The "jdks" field is itself is an object whose field names
        are JDK identifiers and whose field values include a version. For example:

        {
          "jdks": {
            "openjdk8":           {"version": "8u302+02-jvmci-21.2-b02" },
            "labsjdk-ce-11":      {"version": "ce-11.0.11+8-jvmci-21.2-b02" },
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
            "labsjdk-ce-11": {
              "filename": "labsjdk-{version}-{platform}",
              "url": "https://github.com/graalvm/labs-openjdk-11/releases/download/{version|jvmci}/{filename}.tar.gz"
            }
          }
        }

        The "jdk-binaries.<id>" object specifies the URL at which a JDK binary for the "jdks.<id>" object is found.
        The "filename" and "url" attributes of a JDK binary object are template strings with curly braces denoting
        keywords that will be replaced with their values. The supported keywords and their value for a
        "jdk-binaries.<id>" object are:

        version    The value of "jdks.<id>.version".
        platform   The value denoting the operating system and architecture (e.g. "linux-amd64").
        filename   The value of "jdk-binaries.<id>.filename".

        Each keyword value can be processed by a filter by appending "|<filter>" to the keyword selector.
        The supported filters are:

        jvmci      Extracts the first string that looks like a jvmci version (e.g. "jvmci-21.2-b01" -> "21.2-b01").
    """)


    parser.add_argument('--jdk-id', '--java-distribution', action='store', metavar='<id>', help='Identifier of the JDK that should be downloaded (e.g., "labsjdk-ce-11" or "openjdk8")')
    parser.add_argument('--configuration', action='store', metavar='<path>', help='location of JSON file containing JDK definitions (default: {})'.format(default_jdk_versions_location))
    parser.add_argument('--jdk-binaries', action='store', metavar='<path>', help='{} separated JSON files specifying location of JDK binaries (default: {})'.format(os.pathsep, default_jdk_binaries_location))
    parser.add_argument('--to', action='store', metavar='<dir>', help='location where JDK will be installed (default: {})'.format(settings["base-path"]))
    parser.add_argument('--alias', action='store', metavar='<path>', help='path of a symlink to create to the extracted JDK. A relative path will be resolved against the value of the --to option.')
    parser.add_argument('--keep-archive', action='store_true', help='keep downloaded JDK archive')
    parser.add_argument('--strip-contents-home', action='store_true', help='strip Contents/Home if it exists from installed JDK')
    args = parser.parse_args(args)

    if args.to is not None:
        settings["base-path"] = args.to

    if not _check_write_access(settings["base-path"]):
        mx.abort("JDK installation directory {} is not writeable.".format(settings["base-path"]) + os.linesep +
                "Either re-run with elevated privileges (e.g. sudo) or specify a writeable directory with the --to option.")

    jdk_versions_location = _check_exists_or_None(args.configuration) or default_jdk_versions_location
    jdk_binaries_locations = (args.jdk_binaries or default_jdk_binaries_location).split(os.pathsep)

    jdk_versions = _parse_jdk_versions(jdk_versions_location)
    jdk_binaries = _parse_jdk_binaries(jdk_binaries_locations, jdk_versions)

    if args.jdk_id is not None:
        settings["jdk-binary"] = _get_jdk_binary_or_abort(jdk_binaries, args.jdk_id)
    else:
        settings["jdk-binary"] = _choose_jdk_binary(jdk_binaries, is_quiet())

    if args.alias is not None:
        settings["alias"] = args.alias

    if args.keep_archive is not None:
        settings["keep-archive"] = args.keep_archive

    settings["strip-contents-home"] = args.strip_contents_home

    return settings

def _get_jdk_binary_or_abort(jdk_binaries, jdk_id):
    jdk_binary = jdk_binaries.get(jdk_id)
    if not jdk_binary:
        mx.abort("Unknown JDK identifier: {} [Known JDKs: {}]".format(jdk_id, ', '.join(jdk_binaries.keys())))
    return jdk_binary

def _parse_json(path):
    with open(path) as fp:
        try:
            return json.load(fp)
        except ValueError as e:
            mx.abort('The file ({}) does not contain legal JSON: {}'.format(path, e))

def _get_json_attr(json_object, name, expect_type, source):
    value = json_object.get(name) or mx.abort('{}: missing "{}" attribute'.format(source, name))
    if not isinstance(value, expect_type):
        mx.abort('{} -> "{}": value ({}) must be a {}, not a {}'.format(source, name, value, expect_type.__name__, value.__class__.__name__))
    return value

def _parse_jdk_versions(path):
    obj = _parse_json(path)
    return {jdk_id: _get_json_attr(jdk_obj, 'version', str, '{} -> "jdks" -> "{}"'.format(path, jdk_id)) for jdk_id, jdk_obj in _get_json_attr(obj, 'jdks', dict, path).items()}

def _parse_jdk_binaries(paths, jdk_versions):
    jdk_binaries = {}
    for path in paths:
        if not exists(path):
            mx.abort("File doesn't exist: " + path)

        obj = _parse_json(path)

        for qualified_jdk_id, config in _get_json_attr(obj, 'jdk-binaries', dict, path).items():
            source = '{} -> "jdk-binaries" -> "{}"'.format(path, qualified_jdk_id)
            def get_entry(name):
                value = config.get(name) or mx.abort('{}: missing "{}" attribute'.format(source, name))
                if not isinstance(value, str):
                    mx.abort('{} -> "{}": value ({}) must be a string, not a {}'.format(source, name, value, value.__class__.__name__))
                return value

            jdk_id, qualifier = qualified_jdk_id.split(':', 1) if ':' in qualified_jdk_id else (qualified_jdk_id, '')

            version = jdk_versions.get(jdk_id)
            jdk_binary_id = jdk_id + qualifier
            if version and not jdk_binary_id in jdk_binaries:
                jdk_binary = _JdkBinary(jdk_binary_id, version, get_entry('filename'), get_entry('url'), source)
                jdk_binaries[jdk_binary_id] = jdk_binary
    return jdk_binaries

def _default_base_path():
    locations = {
        "darwin": '/Library/Java/JavaVirtualMachines',
        "linux" : '/usr/lib/jvm',
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

def _choose_jdk_binary(jdk_binaries, quiet=False):
    if quiet:
        return _get_jdk_binary_or_abort(jdk_binaries, _DEFAULT_JDK_ID)

    index = 1
    default_choice = 1
    choices = sorted(jdk_binaries.items())
    for jdk_id, jdk_binary in choices:
        if jdk_id == _DEFAULT_JDK_ID:
            default_choice = index
            default = "*"
        else:
            default = " "
        prefix = '[{index}]{default}'.format(index=index, default=default)

        print("{prefix:5} {jdk_id} | {version}".format(prefix=prefix,
        jdk_id=jdk_id.ljust(25), version=jdk_binary._version))
        index += 1
    while True:
        try:
            try:
                choice = input("Select JDK> ")
            except SyntaxError: # Empty line
                choice = ""

            if choice == "":
                index = default_choice - 1
            else:
                index = int(choice) - 1

            if index < 0:
                raise IndexError
            return choices[index][1]
        except (SyntaxError, NameError, IndexError):
            mx.warn("Invalid selection!")

_DEFAULT_JDK_ID = "labsjdk-ce-11"

class _JdkBinary(object):

    def __init__(self, jdk_id, version, filename, url, source):
        self._jdk_id = jdk_id
        self._version = version
        platform = mx.get_os() + '-' + mx.get_arch()
        keywords = {'version': version, 'platform': platform}
        self._filename = _instantiate(filename, keywords, source)
        keywords['filename'] = self._filename
        self._short_version = _instantiate('{version|jvmci}', keywords, source)
        self._url = _instantiate(url, keywords, source)
        self._archive = self._url[self._url.rfind(self._filename):]

    def __repr__(self):
        return '{}: file={}, url={}'.format(self._jdk_id, self._filename, self._url)

    def get_folder_name(self):
        return "{}-{}".format(self._jdk_id, self._short_version)

    def get_final_path(self, jdk_path):
        return join(jdk_path, self.get_folder_name())


_instantiate_filters = {
    'jvmci': lambda value: re.sub(r".*jvmci-(\d+\.\d+-b\d+).*", r"\1", value)
}

def _instantiate(template, keywords, source):
    def repl(match):
        parts = match.group(1).split('|')
        keyword = parts[0]
        filters = parts[1:]
        if keyword not in keywords:
            mx.abort('{}: Error instantiating "{}": "{}" is an unrecognized keyword.\nSupported keywords: "{}"'.format(source, template, keyword, '", "'.join(sorted(keywords.keys()))))
        res = keywords[keyword]

        for f in filters:
            func = _instantiate_filters.get(f)
            if not func:
                mx.abort('{}: Error instantiating "{}": "{}" is an unrecognized filter.\nSupported filters: "{}"'.format(source, template, f, '", "'.join(sorted(_instantiate_filters.keys()))))
            res = func(res)
        return res
    return re.sub(r'{([^}]+)}', repl, template)
