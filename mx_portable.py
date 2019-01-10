#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2019, Oracle and/or its affiliates. All rights reserved.
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

#
# This is a *private* module providing a *temporary* portability
# layer for mx to run on python 2 or 3. Once all known suites have been
# converted to run on python 3, this module will be removed. For this
# reason, this module must *not* be used by suites outside the mx repository.
#

import sys
import itertools
import subprocess

if sys.version_info[0] < 3:
    from StringIO import StringIO                   #pylint: disable=unused-import
    import __builtin__ as builtins                  #pylint: disable=unused-import
    import urllib2                                  #pylint: disable=unused-import
    urllib_request = urllib2
    urllib_error = urllib2
    del urllib2
    import urlparse as urllib_parse                 #pylint: disable=unused-import

    _filter = itertools.ifilter
    _cmp = cmp                                      #pylint: disable=undefined-variable
    _raw_input = raw_input                          #pylint: disable=undefined-variable
    _unicode = unicode                              #pylint: disable=undefined-variable
    _long = long                                    #pylint: disable=undefined-variable
    _basestring = basestring                        #pylint: disable=undefined-variable

    def _py3_decode(x):
        return x
    def _py3_encode(x):
        return x

    def _func_code(f):
        return f.func_code

    def _viewkeys(dictionary):
        return dictionary.viewkeys()
else:
    from io import StringIO                         #pylint: disable=unused-import
    import builtins                                 #pylint: disable=unused-import
    import urllib.request as urllib_request         #pylint: disable=unused-import,no-name-in-module
    import urllib.error as urllib_error             #pylint: disable=unused-import,no-name-in-module
    import urllib.parse as urllib_parse             #pylint: disable=unused-import,no-name-in-module

    _filter = filter
    def _cmp(a, b):
        return (a > b) - (a < b)

    _raw_input = input
    _unicode = str
    _long = int
    _basestring = str

    def _py3_decode(x):
        return x.decode()
    def _py3_encode(x):
        return x.encode()

    def _func_code(f):
        return f.__code__

    def _viewkeys(dictionary):
        return dictionary.keys()

def _check_output(*args, **kwargs):
    return _py3_decode(subprocess.check_output(*args, **kwargs))
