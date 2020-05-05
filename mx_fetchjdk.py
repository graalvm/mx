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
from os.path import join, exists, abspath, isdir, islink
from shutil import copytree
from argparse import ArgumentParser, REMAINDER

from mx import optional_suite_context, _mx_home, command
from jdk_distribution_parser import JdkDistribution
import mx, mx_urlrewrites

@command('mx', 'fetch-jdk', '[options]')
@optional_suite_context
def fetch_jdk(args):
    """fetches required JDK version

    If called without --quiet flag, menu will be printed for available JDK selection.
    """
    args = _parse_fetchjdk_settings(args)

    distribution = args["java-distribution"]
    jdk_path = args["jdk-path"]
    jdk_artifact = distribution.get_jdk_folder()
    full_jdk_path = distribution.get_full_jdk_path(jdk_path)
    jdk_url = mx_urlrewrites.rewriteurl(distribution.get_url())
    jdk_url_sha = jdk_url + ".sha1"
    jdk_archive = distribution.get_archive()

    if not args["quiet"] and not mx.ask_yes_no("Install {} to {}".format(jdk_artifact, jdk_path), default='y'):
            mx.abort("JDK installation canceled")

    if not exists(full_jdk_path):
        if not args["quiet"]:
            print("Fetching {} archive...".format(jdk_artifact))

        archive_location = join(jdk_path, jdk_archive)
        mx._opts.no_download_progress = args["quiet"]
        try:
            sha1_hash = mx._hashFromUrl(jdk_url_sha)
        except:
            mx.abort("Error fetching sha1 hash, check your download location")
        if not exists(archive_location) or not args["keep-archive"]:
            mx.download_file_with_sha1(jdk_artifact, archive_location, [jdk_url], sha1_hash, archive_location + '.sha1', resolve=True, mustExist=True, sources=False)
        untar = mx.TarExtractor(archive_location)

        if not args["quiet"]:
            print("Installing {} to {}...".format(jdk_artifact, jdk_path))

        with untar._open() as tar_file:
            curr_full_jdk_path = untar._getnames(tar_file)[0]

        try:
            untar.extract(jdk_path)
        except:
            os.remove(join(jdk_path, jdk_archive))
            shutil.rmtree(curr_full_jdk_path)
            mx.abort("Error parsing archive. Please try again")
        if not args["keep-archive"]:
            os.remove(join(jdk_path, jdk_archive))
            os.remove(archive_location + '.sha1')
        os.rename(join(jdk_path, curr_full_jdk_path), full_jdk_path)

    elif not args["quiet"]:
        mx.warn("Requested JDK was already present")

    if mx.is_darwin() and exists(join(full_jdk_path, 'Contents', 'Home')):
        if args["strip-contents-home"]:
            tmp_full_jdk_path = full_jdk_path + ".tmp"
            shutil.move(full_jdk_path, tmp_full_jdk_path)
            shutil.move(join(tmp_full_jdk_path, 'Contents', 'Home'), full_jdk_path)
            shutil.rmtree(tmp_full_jdk_path)
        else:
            full_jdk_path = join(full_jdk_path, 'Contents', 'Home')

    if "alias" in args:
        alias_full_path = join(jdk_path, args["alias"])
        if exists(alias_full_path) or islink(alias_full_path):
            if isdir(alias_full_path) and not islink(alias_full_path):
                shutil.rmtree(alias_full_path)
            else:
                os.remove(alias_full_path)

        if not (mx.is_windows() or mx.is_cygwin()):
            os.symlink(full_jdk_path, alias_full_path)
        else:
            copytree(full_jdk_path, alias_full_path, symlinks=True) # fallback for windows
        full_jdk_path = alias_full_path

    if not args["quiet"]:
        print("Run the following to set JAVA_HOME in your shell:")

    print('export JAVA_HOME={}'.format(abspath(full_jdk_path)))


def _parse_fetchjdk_settings(args):
    settings = {}
    settings["quiet"] = False
    settings["keep-archive"] = False
    settings["jdk-path"] = default_jdk_path()

    common_location = join(_mx_home, 'common.json')

    parser = ArgumentParser(prog='mx fetch-jdk')
    parser.add_argument('--java-distribution', action='store', help='JDK distribution that should be downloaded (e.g., "labsjdk-ce-11" or "openjdk8")')
    parser.add_argument('--configuration', action='store', help='location of configuration json file (default: \'{}\')'.format(common_location))
    parser.add_argument('--to', action='store', help='location where JDK would be downloaded (default: \'{}\')'.format(settings["jdk-path"]))
    parser.add_argument('--alias', action='store', help='name of symlink to JDK')
    parser.add_argument('--keep-archive', action='store_true', help='keep downloaded JDK archive')
    if mx.is_darwin():
        parser.add_argument('--strip-contents-home', action='store_true', help='strip Contents/Home')
    parser.add_argument('-q', '--quiet', action='store_true', help='suppress logging output')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.quiet is not None:
        settings["quiet"] = args.quiet

    if args.to is not None:
        settings["jdk-path"] = args.to
    elif not settings["quiet"]:
        mx.warn("JDK location hasn't been specified. Using {}".format(settings["jdk-path"]))

    if not check_access_jdk_path(settings["jdk-path"]):
        warning_msg = "Path '{}' is not writable (try running with elevated privileges). ".format(settings["jdk-path"])
        settings["jdk-path"] = abspath(join("bin", "jdks"))
        warning_msg += os.linesep + "Trying to fall back to {}".format(settings["jdk-path"])
        if not settings["quiet"]:
            mx.warn(warning_msg)
        if not check_access_jdk_path(settings["jdk-path"]):
            mx.abort("Path '{}' is not writable (try running with elevated privileges). ".format(settings["jdk-path"]))

    if args.configuration is not None:
        common_location = args.configuration
    else:
        if mx.primary_suite() is not None:
            common_location = join(mx.primary_suite().vc_dir, 'common.json') # Try fetching suite config
        else:
            common_location = join(os.getcwd(), 'common.json') # Fallback to same folder
            if not exists(common_location):
                common_location = join(_mx_home, 'common.json') # Fallback to mx
            if not settings["quiet"]:
                mx.warn("Selected `{}` as configuration location, since no location is provided".format(common_location))
    if not exists(common_location):
        mx.abort("Configuration file doesn't exist")

    parse_common_json(common_location)

    if args.java_distribution is not None:
        settings["java-distribution"] = JdkDistribution.by_name(args.java_distribution)
    else:
        settings["java-distribution"] = JdkDistribution.choose_dist(settings["quiet"])

    if args.alias is not None:
        settings["alias"] = args.alias

    if args.keep_archive is not None:
        settings["keep-archive"] = args.keep_archive

    if mx.is_darwin() and args.strip_contents_home is not None:
        settings["strip-contents-home"] = True

    return settings

def parse_common_json(common_path):
    with open(common_path) as common_file:
        common_cfg = json.load(common_file)

    for distribution in common_cfg["jdks"]:
        JdkDistribution.parse(distribution, common_cfg["jdks"][distribution]["version"])

def default_jdk_path():
    locations = {
        "darwin": '/Library/Java/JavaVirtualMachines',
        "linux" : '/usr/lib/jvm',
        "solaris": '/usr/jdk/instances',
        "windows": r'C:\Program Files\Java'
    }
    return locations[mx.get_os()]

def check_access_jdk_path(jdk_path):
    try:
        if not exists(jdk_path):
            os.makedirs(jdk_path)
        if not os.access(jdk_path, os.W_OK):
            raise IOError
        return True
    except (IOError, OSError):
        return False
