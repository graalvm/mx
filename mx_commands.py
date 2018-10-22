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
from functools import wraps

import mx_primary_suite

_commands = {}

_commandsToSuite = {}


def _command_function(name, fatal_if_missing):
    if name in _commands:
        return _commands[name][0]
    else:
        if fatal_if_missing:
            import mx
            mx.abort('command ' + name + ' does not exist')
        else:
            return None


def _update_commands(new_commands, suite=None):
    for key, value in new_commands.iteritems():
        assert ':' not in key
        old = _commands.get(key)
        if old is not None:
            old_suite = _commandsToSuite.get(key)
            if not old_suite:
                # Core mx command is overridden by first suite
                # defining command of same name. The core mx
                # command has its name prefixed with ':'.
                _commands[':' + key] = old
            else:
                # Previously specified command from another suite
                # is made available using a qualified name.
                # The last (primary) suite (depth-first init) always defines the generic command
                # N.B. Dynamically loaded suites loaded via Suite.import_suite register after the primary
                # suite but they must not override the primary definition.
                if old_suite == mx_primary_suite._primary_suite:
                    # ensure registered as qualified by the registering suite
                    key = suite.name + ':' + key
                else:
                    qualified_key = old_suite.name + ':' + key
                    _commands[qualified_key] = old

        _commands[key] = value
        if suite:
            _commandsToSuite[key] = suite


def _format_commands():
    msg = '\navailable commands:\n'
    msg += _list_commands(sorted([k for k in _commands.iterkeys() if ':' not in k]) + sorted([k for k in _commands.iterkeys() if ':' in k]))
    return msg + '\n'


def _list_commands(l):
    msg = ""
    for cmd in l:
        c, _ = _commands[cmd][:2]
        doc = c.__doc__
        if doc is None:
            doc = ''
        msg += ' {0:<20} {1}\n'.format(cmd, doc.split('\n', 1)[0])
    return msg


def get_command_property(command, property_name):
    c = _commands.get(command)
    if c and len(c) >= 4:
        props = c[3]
        if props and property_name in props:
            return props[property_name]
    return None


_command_callbacks = []


def add_command_callback(callback):
    _command_callbacks.append(callback)


def remove_command_callback(callback):
    _command_callbacks.remove(callback)


def suite_command(suite, command, usage_msg=None, doc_function=None, auto_add=True):
    if suite is None:
        raise ValueError('suite must be defined')
    return _mx_command(suite, command, usage_msg, doc_function, auto_add)


def mx_command(command, usage_msg=None, doc_function=None, auto_add=True):
    return _mx_command(None, command, usage_msg, doc_function, auto_add)


def _mx_command(suite, command, usage_msg=None, doc_function=None, auto_add=True):
    def mx_command_decorator(command_func):
        @wraps(command_func)
        def mx_command_wrapped(*args, **kwargs):
            for callback in _command_callbacks:
                callback(command, usage_msg, doc_function, *args, **kwargs)

            return command_func(*args, **kwargs)

        if auto_add:
            _update_commands({
                command: [mx_command_wrapped, usage_msg, doc_function]
            }, suite)
        return mx_command_wrapped

    return mx_command_decorator


def command_function(name, fatalIfMissing=True):
    """
    Return the function for the (possibly overridden) command named `name`.
    If no such command, abort if `fatalIsMissing` is True, else return None
    """
    return _command_function(name, fatalIfMissing)


def update_commands(suite, new_commands):
    """
    Using the decorator mx_commands.mx_commands is preferred over this function.

     :param suite: for which the command is added.
    :param new_commands: Keys are command names, value are lists: [<function>, <usage msg>, <format args to doc string of function>...]
    If any of the format args are instances of Callable, then they are called with an 'env' are before being
    used in the call to str.format().
    """
    _update_commands(new_commands, suite)
