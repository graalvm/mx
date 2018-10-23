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


class MxCommands(object):
    def __init__(self, blessed_suite_name):
        self._commands = {}
        self._commands_to_suite_name = {}
        self._command_callbacks = []
        self._blessed_suite_name = blessed_suite_name

    def commands(self):
        return self._commands.copy()

    def list_commands(self, l):
        msg = ""
        for cmd in l:
            c, _ = self._commands[cmd][:2]
            doc = c.__doc__
            if doc is None:
                doc = ''
            msg += ' {0:<20} {1}\n'.format(cmd, doc.split('\n', 1)[0])
        return msg

    def add_command_callback(self, callback):
        self._command_callbacks.append(callback)

    def remove_command_callback(self, callback):
        self._command_callbacks.remove(callback)

    def get_command_property(self, command, property_name):
        c = self._commands.get(command)
        if c and len(c) >= 4:
            props = c[3]
            if props and property_name in props:
                return props[property_name]
        return None

    def command_function(self, name, fatal_if_missing=True):
        """
        Return the function for the (possibly overridden) command named `name`.
        If no such command, abort if `fatal_is_missing` is True, else return None
        """
        if name in self._commands:
            return self._commands[name][0]
        else:
            if fatal_if_missing:
                import mx
                mx.abort('command ' + name + ' does not exist')
            else:
                return None

    def update_commands(self, suite_name, new_commands):
        """
        Using the decorator mx_commands.mx_commands is preferred over this function.

        :param suite_name: for which the command is added.
        :param new_commands: Keys are command names, value are lists: [<function>, <usage msg>, <format doc function>]
        If any of the format args are instances of Callable, then they are called with an 'env' are before being
        used in the call to str.format().
        """
        assert suite_name is not None
        for key, value in new_commands.iteritems():
            assert ':' not in key
            old = self._commands.get(key)
            if old is not None:
                old_suite_name = self._commands_to_suite_name.get(key)
                if old_suite_name is self._blessed_suite_name:
                    # Core mx command is overridden by first suite
                    # defining command of same name. The core mx
                    # command has its name prefixed with ':'.
                    self._commands[':' + key] = old
                else:
                    self._commands[old_suite_name + ':' + key] = old

            self._commands[key] = value
            self._commands_to_suite_name[key] = suite_name

    def mx_command(self, suite, command, usage_msg=None, doc_function=None, props=None, auto_add=True):
        def mx_command_decorator(command_func):
            @wraps(command_func)
            def mx_command_wrapped(*args, **kwargs):
                for callback in self._command_callbacks:
                    callback(command, usage_msg, doc_function, props, *args, **kwargs)

                return command_func(*args, **kwargs)

            if auto_add:
                self.update_commands(suite, {
                    command: [mx_command_wrapped, usage_msg, doc_function]
                })
            return mx_command_wrapped

        return mx_command_decorator
