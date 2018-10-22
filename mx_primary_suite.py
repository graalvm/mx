#!/usr/bin/env python2.7
#
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
#
import os

_primary_suite_path = None
_primary_suite = None
# List of functions to run when the primary suite is initialized
_primary_suite_deferrables = []


def _init(s):
    global _primary_suite
    assert not _primary_suite
    _primary_suite = s
    _primary_suite.primary = True
    os.environ['MX_PRIMARY_SUITE_PATH'] = s.dir
    for deferrable in _primary_suite_deferrables:
        deferrable()


def add_primary_suite_deferrable(deferrable):
    _primary_suite_deferrables.append(deferrable)


def primary_suite():
    """:rtype: Suite"""
    return _primary_suite
