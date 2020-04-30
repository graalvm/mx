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
import os, shutil
from os.path import join, exists, abspath, isdir, islink
from shutil import copytree
from argparse import ArgumentParser, REMAINDER

from mx import optional_suite_context, _mx_home, command
from select_jdk import find_system_jdks
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
    jdk_folder = distribution.get_jdk_folder()
    full_jdk_path = distribution.get_full_jdk_path(jdk_path)
    jdk_url = mx_urlrewrites.rewriteurl(distribution.get_url())
    jdk_archive = distribution.get_archive()

    if not exists(full_jdk_path):
        mx._opts.no_download_progress = args["quiet"]
        mx.download(join(jdk_path, jdk_archive), [jdk_url], verbose=not args["quiet"])
        untar = mx.TarExtractor(join(jdk_path, jdk_archive))

        if not args["quiet"]:
            print("Installing...")

        with untar._open() as tar_file:
            curr_full_jdk_path = untar._getnames(tar_file)[0]

        untar.extract(jdk_path)
        if not args["keep-archive"]:
            os.remove(join(jdk_path, jdk_archive))
        os.rename(join(jdk_path, curr_full_jdk_path), full_jdk_path)

    if mx.get_os() == 'darwin':
        full_jdk_path = join(full_jdk_path, 'Contents', 'Home')

    if "alias" in args:
        alias_full_path = join(jdk_path, args["alias"])
        if exists(alias_full_path) or islink(alias_full_path):
            if isdir(alias_full_path) and not islink(alias_full_path):
                shutil.rmtree(alias_full_path)
            else:
                os.remove(alias_full_path)

        if not (mx.is_windows() or mx.is_cygwin()):
            os.symlink(jdk_folder, alias_full_path)
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
    settings["jdk-path"] = abspath(join('bin', 'jdks'))

    jdk_paths = find_system_jdks()
    if len(jdk_paths) > 0:
        settings["jdk-path"] = jdk_paths[0]
        found_jdk_path = True
    else:
        found_jdk_path = False

    common_location = join(_mx_home, 'common.json')

    parser = ArgumentParser(prog='mx fetch-labsjdk')
    parser.add_argument('--java-distribution', action='store', help='JDK distribution that should be downloaded (e.g., "labsjdk-ce-11" or "openjdk8")')
    parser.add_argument('--configuration', action='store', help='location of configuration json file (default: \'{}\')'.format(common_location))
    parser.add_argument('--to', action='store', help='location where JDK would be downloaded (default: \'{}\')'.format(settings["jdk-path"]))
    parser.add_argument('--alias', action='store', help='name of symlink to JDK')
    parser.add_argument('--keep-archive', action='store_true', help='keep downloaded JDK archive')
    parser.add_argument('-q', '--quiet', action='store_true', help='suppress logging output')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.quiet is not None:
        settings["quiet"] = args.quiet

    if args.to is not None:
        settings["jdk-path"] = args.to
    elif not found_jdk_path and not settings["quiet"]:
        mx.warn("No standard JDK location. Using {}".format(settings["jdk-path"]))

    try:
        test_location = join(settings["jdk-path"], "test")
        test_file = open(test_location, 'w')
        test_file.close()
        os.remove(test_location)
    except IOError:
        mx.abort("Path '"+settings["jdk-path"]+"' is not writable. " + os.linesep +
        "Rerun command with elevated privileges, or choose different JDK download location.")

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

    JdkDistribution.parse_common_json(common_location)

    if args.java_distribution is not None:
        settings["java-distribution"] = JdkDistribution.by_name(args.java_distribution)
    else:
        settings["java-distribution"] = JdkDistribution.choose_dist(settings["quiet"])

    if args.keep_archive is not None:
        settings["keep-archive"] = args.keep_archive

    if args.alias is not None:
        settings["alias"] = args.alias

    return settings
