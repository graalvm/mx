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

class MxCommands(object):
    def __init__(self, blessed_suite_name):
        self._commands = {}
        self._commands_to_suite_name = {}
        self._blessed_suite_name = blessed_suite_name
        self._command_before_callbacks = []
        self._command_after_callbacks = []

    @property
    def command_before_callbacks(self):
        return list(self._command_before_callbacks)

    @property
    def command_after_callbacks(self):
        return list(self._command_after_callbacks)

    def add_command_callback(self, callback_before=None, callback_after=None):
        assert not (callback_before is None and callback_after is None)

        if callback_before is not None:
            self._command_before_callbacks.append(callback_before)
        if callback_after is not None:
            self._command_after_callbacks.append(callback_after)

    def remove_command_callback(self, callback_before=None, callback_after=None):
        assert not (callback_before is None and callback_after is None)
        if callback_before is not None:
            self._command_before_callbacks.remove(callback_before)
        if callback_after is not None:
            self._command_after_callbacks.remove(callback_after)

    def commands(self):
        return self._commands.copy()

    def list_commands(self, l):
        msg = ""
        for cmd in l:
            doc = self._commands[cmd].command_function.__doc__
            if doc is None:
                doc = ''
            doc_lines = doc.split('\n', 1)[0]
            msg += f' {cmd:<20} {doc_lines}\n'
        return msg

    def get_command_property(self, command, property_name):
        c = self._commands.get(command)
        if c.props:
            if property_name in c.props:
                return c.props[property_name]
        return None

    def command_function(self, name, fatal_if_missing=True):
        """
        Return the function for the (possibly overridden) command named `name`.
        If no such command, abort if `fatal_is_missing` is True, else return None
        """
        if name in self._commands:
            return self._commands[name]
        else:
            if fatal_if_missing:
                import mx
                mx.abort('command ' + name + ' does not exist')
            else:
                return None

    def add_commands(self, new_commands):
        for mx_command in new_commands:
            key = mx_command.command
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

            self._commands[key] = mx_command
            self._commands_to_suite_name[key] = mx_command.suite_name


class MxCommand(object):

    def __init__(self, mx_commands, command_function, suite_name, command, usage_msg='', doc_function=None, props=None):
        self._mx_commands = mx_commands
        self._command_function = command_function
        self.suite_name = suite_name
        self.command = command
        self.usage_msg = usage_msg
        self.doc_function = doc_function
        self.props = props

    @property
    def command_function(self):
        return self._command_function

    def get_doc(self):
        doc = 'mx {0} {1}'
        msg = '<no documentation>'
        if self.command_function.__doc__ or self.doc_function or self.usage_msg:
            msg = ''
            if self.usage_msg:
                msg += self.usage_msg
            if self.command_function.__doc__:
                msg += '\n\n' + self.command_function.__doc__
            if self.doc_function:
                msg += '\n' + self.doc_function()

        return doc.format(self.command, msg)

    def __call__(self, *args, **kwargs):
        for callback in self._mx_commands.command_before_callbacks:
            callback(self, *args, **kwargs)
        try:
            return self.command_function(*args, **kwargs)
        finally:
            for callback in self._mx_commands.command_after_callbacks:
                callback(self, *args, **kwargs)
