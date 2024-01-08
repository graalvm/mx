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

from __future__ import annotations

__all__ = ["get_env", "check_get_env", "env_var_to_bool", "str_to_bool"]

import os
from typing import TypeVar

from .logging import abort


def check_get_env(key) -> str:
    """
    Gets an environment variable, aborting with a useful message if it is not set.
    """
    value = get_env(key)
    if value is None:
        return abort(f"Required environment variable '{key}' must be set")
    return value


Ty = TypeVar("Ty")


def get_env(key: str, default: Ty = None) -> str | Ty:
    """
    Gets an environment variable.
    :param default: default values if the environment variable is not set.
    """
    value = os.getenv(key, default)
    return value


def str_to_bool(val: str) -> bool:
    low_val = val.lower()
    if low_val in ("false", "0", "no"):
        return False
    elif low_val in ("true", "1", "yes"):
        return True
    return abort(f"Unexpected string to bool value {val}")


def env_var_to_bool(name: str, default: str = "false") -> bool:
    val = get_env(name, default)
    return str_to_bool(val)
