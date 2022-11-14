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
import json
import os
import re
import subprocess

from multiprocessing import Lock

import mx

_bear_version_regex = re.compile(r"bear ([0-9]+).([0-9]+).([0-9]+)", re.IGNORECASE)
_bear_version = '<uninitialized>'

def _get_bear_version():
    global _bear_version
    if _bear_version == '<uninitialized>':
        try:
            output = mx._check_output_str(['bear', '--version'], stderr=subprocess.STDOUT)
        except OSError:
            output = ''
        m = _bear_version_regex.search(output)
        if m:
            _bear_version = int(m.group(1))
        else:
            mx.warn("Could not find bear, will not produce compilation database for make projects.")
            _bear_version = None
    return _bear_version


def gmake_with_bear(out=None, append=False, context=None):
    v = _get_bear_version()
    if v is None:
        return [mx.gmake_cmd(context=context)]
    else:
        ret = ['bear']
        if append:
            ret.append('--append' if v >= 3 else '-a')
        if out is not None:
            ret.append('--output' if v >= 3 else '-o')
            ret.append(out)
        if v >= 3:
            ret.append('--')
        ret.append(mx.gmake_cmd(context=context))
        return ret


_compdb_path = None
_compdb_lock = None

def _default_compdb_path():
    suite = mx.primary_suite()
    if suite is None:
        # no primary suite, don't try to enable compdb
        return None
    if suite.vc_dir:
        return os.path.join(os.path.dirname(suite.vc_dir), 'compile_commands.json')
    else:
        return os.path.join(suite.dir, 'compile_commands.json')


def init():
    global _compdb_path
    global _compdb_lock
    o = mx.get_opts().compdb
    if o is None:
        o = mx.get_env('MX_COMPDB')
    if o is not None and o != 'none':
        _compdb_lock = Lock()
        if o == 'default':
            _compdb_path = _default_compdb_path()
        else:
            _compdb_path = os.path.abspath(o)

def enabled():
    return _compdb_path is not None

def gmake_with_compdb_cmd(context=None):
    if enabled():
        return gmake_with_bear(append=True, context=context)
    else:
        return [mx.gmake_cmd(context=context)]

class Compdb:
    def __init__(self):
        self.content = {}

    def __enter__(self):
        _compdb_lock.acquire()
        if os.path.exists(_compdb_path):
            self.mergeFile(_compdb_path)
        return self

    def __exit__(self, *args):
        with open(_compdb_path, 'w') as f:
            json.dump(list(self.content.values()), f, indent=4)
        _compdb_lock.release()

    def merge(self, data):
        for item in data:
            key = item['file']
            if not os.path.isabs(key):
                key = os.path.normpath(os.path.join(item['directory'], item['file']))
            self.content[item['file']] = item

    def mergeString(self, string):
        try:
            self.merge(json.loads(string))
        except json.JSONDecodeError:
            mx.warn("Error decoding JSON compilation database. Ignoring.")

    def mergeFile(self, path):
        with open(path, 'r') as f:
            try:
                self.merge(json.load(f))
            except json.JSONDecodeError:
                mx.warn(f"Error decoding JSON compilation database from '{path}'. Ignoring.")


class CompdbCapture:
    def __init__(self, suite):
        self.data = ""

    def __call__(self, data):
        self.data += data

    def __enter__(self):
        if enabled():
            return self
        else:
            return None

    def __exit__(self, *args):
        if enabled():
            with Compdb() as db:
                db.mergeString(self.data)

def merge_compdb(subject, path):
    if enabled():
        with Compdb() as db:
            inFile = os.path.join(path, 'compile_commands.json')
            if os.path.exists(inFile):
                db.mergeFile(inFile)
            else:
                mx.warn(f"JSON compilation database for {subject} not found (expected at {inFile}).")
