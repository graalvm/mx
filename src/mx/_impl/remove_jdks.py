#!/usr/bin/env python3
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
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

from argparse import ArgumentParser
import os, shutil
import select_jdk

if __name__ == '__main__':
    parser = ArgumentParser(prog='remove_jdks', usage='%(prog)s [options]' + """
        Removes JDKs available to the select_jdk command.""")

    parser.add_argument('-f', '--force', action='store_true', help='remove selected JDKs without confirmation')
    args = parser.parse_args()

    jdks = select_jdk.choose_jdks()
    if jdks:
        for jdk in jdks:
            jdk_base = jdk.java_home
            if jdk_base.endswith('/Contents/Home'):
                jdk_base = jdk_base[0:-len('/Contents/Home')]
            if not args.force:
                answer = input(f'Remove {jdk_base}? [Yn]> ')
                if answer not in ('', 'Y', 'y'):
                    continue
            tmp_jdk_base = f'{jdk_base}.{os.getpid()}'
            try:
                # Move the directory to a new name to make the
                # removal as atomic as possible from the perspective
                # of other processes.
                os.rename(jdk_base, tmp_jdk_base)
            except OSError as e:
                print(e)
                continue
            print(f'Removing {jdk_base}... ', end='')
            shutil.rmtree(tmp_jdk_base)
            print(' done')
