#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2024, 2024, Oracle and/or its affiliates. All rights reserved.
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
"""
Support code to create files with Java arguments that can be passed using the @-syntax (e.g. ``java @argumentsfile``).

Please note that using the @-syntax in an argument file recursively is not supported and will be interpreted by java as
a literal argument.

See also the JAVA COMMAND-LINE ARGUMENT FILES section in ``man 1 java``
"""

__all__ = [
    "write_to_file",
    "escape_argument",
]

import os
from typing import Sequence, TextIO

SPECIAL_CHARS = [" ", "'", '"', "\n", "\r", "\t", "\f"]
"""
If any of these characters appear in an argument, the argument has to be put in double quotes and properly escaped.

Backslashes by themselves don't require quoting, but if the argument is put in quotes, backslashes have to be escaped.
"""


def escape_argument(arg: str) -> str:
    """
    Escapes a single commandline argument for use in a Java argument file.

    The returned argument can be put on its own line or next to other arguments on the same line separated by a space.
    """
    if not arg:
        # Empty arguments need to be quoted, otherwise they are ignored
        return '""'

    if any((c in arg for c in SPECIAL_CHARS)):
        # Argument contains special characters and needs to be put in quotes
        escaped = (
            # Inside quotes, backslashes are escape characters, so any existing backslashes need to be escaped
            arg.replace("\\", "\\\\")
            # Escape quotation marks to not interfere with the surrounding quotes
            .replace("'", "\\'")
            .replace('"', '\\"')
            # Control characters are replaced with their literal escape sequence. These are properly interpreted when
            # the file is read
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
            .replace("\f", "\\f")
        )
        return f'"{escaped}"'
    else:
        # Otherwise, the argument can be used as-is
        return arg


def write_to_file(file: TextIO, args: Sequence[str]) -> None:
    """
    Writes the given arguments in the correct format to the given file opened in text mode.
    One argument per line and arguments are properly escaped according to the semantics of Java argument files.
    """
    for arg in args:
        file.write(escape_argument(arg))
        file.write(os.linesep)
