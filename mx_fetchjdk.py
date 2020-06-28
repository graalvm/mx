#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2020, Oracle and/or its affiliates. All rights reserved.
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
import os, shutil, json
from os.path import join, exists, abspath
from argparse import ArgumentParser, REMAINDER

from mx import optional_suite_context, _mx_home, command, atomic_file_move_with_fallback, is_quiet
from select_jdk import get_setvar_format
from jdk_distribution_parser import JdkDistribution
import mx, mx_urlrewrites

@command('mx', 'fetch-jdk', '[options]')
@optional_suite_context
def fetch_jdk(args):
    """fetches required JDK version

    If mx is not passed the --quiet flag, menu will be printed for available JDK selection.
    """
    args = _parse_fetchsettings(args)

    distribution = args["java-distribution"]
    base_path = args["base-path"]
    artifact = distribution.get_folder_name()
    final_path = distribution.get_final_path(base_path)
    url = mx_urlrewrites.rewriteurl(distribution.get_url())
    sha_url = url + ".sha1"
    archive_name = distribution.get_archive_name()
    archive_target_location = join(base_path, archive_name)

    if not is_quiet():
        if not mx.ask_yes_no("Install {} to {}".format(artifact, final_path), default='y'):
            mx.abort("JDK installation canceled")

    if exists(final_path):
        if args["keep-archive"]:
            mx.warn("The --keep-archive option is ignored when the JDK is already installed.")
        mx.log("Requested JDK is already installed at {}".format(final_path))
    else:
        # Try to extract on the same file system as the target to be able to atomically move the result.
        with mx.TempDir(parent_dir=base_path) as temp_dir:
            mx.log("Fetching {} archive from {}...".format(artifact, url))
            archive_location = join(temp_dir, archive_name)
            mx._opts.no_download_progress = is_quiet()
            sha1_hash = mx._hashFromUrl(sha_url).decode('utf-8')

            mx.download_file_with_sha1(artifact, archive_location, [url], sha1_hash, archive_location + '.sha1', resolve=True, mustExist=True, sources=False)
            untar = mx.TarExtractor(archive_location)

            mx.log("Installing {} to {}...".format(artifact, final_path))

            extracted_path = join(temp_dir, 'extracted')
            try:
                untar.extract(extracted_path)
            except:
                mx.rmtree(temp_dir, ignore_errors=True)
                mx.abort("Error parsing archive. Please try again")

            jdk_root_folder = get_extracted_jdk_archive_root_folder(extracted_path)
            if args["keep-archive"]:
                atomic_file_move_with_fallback(archive_location, archive_target_location)
                atomic_file_move_with_fallback(archive_location + '.sha1', archive_target_location + ".sha1")
                mx.log("Archive is located at {}".format(archive_target_location))

            atomic_file_move_with_fallback(join(extracted_path, jdk_root_folder), final_path)

    curr_path = final_path
    if mx.is_darwin() and exists(join(final_path, 'Contents', 'Home')):
        if args["strip-contents-home"]:
            with mx.TempDir() as tmp_path:
                shutil.move(final_path, join(tmp_path, 'jdk'))
                shutil.move(join(tmp_path, 'jdk', 'Contents', 'Home'), final_path)
        else:
            final_path = join(final_path, 'Contents', 'Home')

    if "alias" in args:
        alias_full_path = join(base_path, args["alias"])
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

def _parse_fetchsettings(args):
    settings = {}
    settings["keep-archive"] = False
    settings["base-path"] = default_base_path()

    common_location = join(_mx_home, 'common.json')

    parser = ArgumentParser(prog='mx fetch-jdk')
    parser.add_argument('--java-distribution', action='store', help='JDK distribution that should be downloaded (e.g., "labsjdk-ce-11" or "openjdk8")')
    parser.add_argument('--configuration', action='store', help='location of configuration json file (default: \'{}\')'.format(common_location))
    parser.add_argument('--to', action='store', help='location where JDK would be downloaded (default: \'{}\')'.format(settings["base-path"]))
    parser.add_argument('--alias', action='store', help='name of symlink to JDK')
    parser.add_argument('--keep-archive', action='store_true', help='keep downloaded JDK archive')
    if mx.is_darwin():
        parser.add_argument('--strip-contents-home', action='store_true', help='strip Contents/Home')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.to is not None:
        settings["base-path"] = args.to

    if not check_write_access(settings["base-path"]):
        mx.abort("JDK installation directory {} is not writeable.".format(settings["base-path"]) + os.linesep +
                "Either re-run with elevated privileges (e.g. sudo) or specify a writeable directory with the --to option.")

    if args.configuration is not None:
        common_location = args.configuration
    else:
        if mx.primary_suite() is not None:
            common_location = join(mx.primary_suite().vc_dir, 'common.json') # Try fetching suite config
        else:
            common_location = join(os.getcwd(), 'common.json') # Fallback to same folder
            if not exists(common_location):
                common_location = join(_mx_home, 'common.json') # Fallback to mx
            mx.warn("Selected `{}` as configuration location, since no location is provided".format(common_location))
    if not exists(common_location):
        mx.abort("Configuration file doesn't exist")

    parse_common_json(common_location)

    if args.java_distribution is not None:
        settings["java-distribution"] = JdkDistribution.by_name(args.java_distribution)
    else:
        settings["java-distribution"] = JdkDistribution.choose_dist(is_quiet())

    if args.alias is not None:
        settings["alias"] = args.alias

    if args.keep_archive is not None:
        settings["keep-archive"] = args.keep_archive

    if mx.is_darwin() and (args.strip_contents_home is not None):
        settings["strip-contents-home"] = args.strip_contents_home

    return settings

def parse_common_json(common_path):
    with open(common_path) as common_file:
        try:
            common_cfg = json.load(common_file)
        except ValueError as e:
            mx.abort('The common.json file ({}) does not contain legal JSON: {}'.format(common_path, e))

    if 'jdks' in common_cfg:
        for distribution in common_cfg['jdks']:
            jdk_description = common_cfg['jdks'][distribution]
            if 'version' in jdk_description:
                JdkDistribution.parse(distribution, jdk_description['version'])
            else:
                mx.abort('Distribution {} does not have a "version" property. Has the common.json({}) layout changed?'.format(distribution, common_path))
    else:
        mx.abort('Could not find property "jdks" in common.json ({}). Has the common.json layout changed?'.format(common_path))

def default_base_path():
    locations = {
        "darwin": '/Library/Java/JavaVirtualMachines',
        "linux" : '/usr/lib/jvm',
        "solaris": '/usr/jdk/instances',
        "windows": r'C:\Program Files\Java'
    }
    return locations[mx.get_os()]

def check_write_access(path):
    try:
        if not exists(path):
            os.makedirs(path)
        if not os.access(path, os.W_OK):
            raise IOError
        return True
    except (IOError, OSError):
        return False

def get_extracted_jdk_archive_root_folder(extracted_archive_path):
    root_folders = os.listdir(extracted_archive_path)
    if len(root_folders) != 1:
        mx.abort("JDK archive layout changed. Please contact the mx maintainers.")
    return root_folders[0]
