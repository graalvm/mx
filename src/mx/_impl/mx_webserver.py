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
from . import mx
from argparse import ArgumentParser
from os.path import join

@mx.command(suite_name="mx",
            command_name='webserver',
            usage_msg='[options] [root]',
            auto_add=False)
@mx.suite_context_free
def webserver(args):
    """start or bundle a simple webserver with a web site"""

    parser = ArgumentParser(prog='mx webserver', description='Start a webserver to serve the site at root or '
                            'bundle the site along with the server into an executable jar.')

    parser.add_argument('-a', '--archive', help='instead of starting the server, create an executable jar in <path> '
                        'containing the server and the site at root such that `java -jar <path>` will start a server '
                        'for the site and open a browser at its root.', metavar='<path>')
    parser.add_argument('-p', '--port', help='local port on which the server should listen', metavar='<num>')
    parser.add_argument('--no-browse', help='do not open default web browser on the served site', action='store_true')
    parser.add_argument('root', metavar='root')

    args = parser.parse_args(args)

    mainClass = join(mx._mx_suite.dir, 'java/com.oracle.mxtool.webserver/src/com/oracle/mxtool/webserver/WebServer.java')
    jdk = mx.get_jdk(tag='default')

    java_args = [mainClass]
    if args.archive:
        java_args.append('--archive=' + args.archive)
    if args.port:
        java_args.append('--port=' + args.port)
    if args.no_browse:
        java_args.append('--no-browse')
    java_args.append(args.root)
    mx.run_java(java_args, jdk=jdk)
