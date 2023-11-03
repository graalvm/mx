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

# https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
_ansi_color_table = {
    'black' : '30',
    'red' : '31',
    'green' : '32',
    'yellow' : '33',
    'blue' : '34',
    'magenta' : '35',
    'cyan' : '36'
    }

def log(msg=None, end='\n'):
    """
    Write a message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if vars(_opts).get('quiet'):
        return
    if msg is None:
        print()
    else:
        # https://docs.python.org/2/reference/simple_stmts.html#the-print-statement
        # > A '\n' character is written at the end, unless the print statement
        # > ends with a comma.
        #
        # In CPython, the normal print statement (without comma) is compiled to
        # two bytecode instructions: PRINT_ITEM, followed by PRINT_NEWLINE.
        # Each of these bytecode instructions is executed atomically, but the
        # interpreter can suspend the thread between the two instructions.
        #
        # If the print statement is followed by a comma, the PRINT_NEWLINE
        # instruction is omitted. By manually adding the newline to the string,
        # there is only a single PRINT_ITEM instruction which is executed
        # atomically, but still prints the newline.
        print(str(msg), end=end)

def logv(msg=None, end='\n'):
    if vars(_opts).get('verbose') is None:
        def _deferrable():
            logv(msg, end=end)
        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.verbose:
        log(msg, end=end)

def logvv(msg=None, end='\n'):
    if vars(_opts).get('very_verbose') is None:
        def _deferrable():
            logvv(msg, end=end)
        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.very_verbose:
        log(msg, end=end)

def log_error(msg=None):
    """
    Write an error message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if msg is None:
        print(file=sys.stderr)
    else:
        print(colorize(str(msg), stream=sys.stderr), file=sys.stderr)

def log_deprecation(msg=None):
    """
    Write an deprecation warning to the console.
    """
    if msg is None:
        print(file=sys.stderr)
    else:
        print(colorize(str(f"[MX DEPRECATED] {msg}"), color='yellow', stream=sys.stderr), file=sys.stderr)

def colorize(msg, color='red', bright=True, stream=sys.stderr):
    """
    Wraps `msg` in ANSI escape sequences to make it print to `stream` with foreground font color
    `color` and brightness `bright`. This method returns `msg` unchanged if it is None,
    if it already starts with the designated escape sequence or the execution environment does
    not support color printing on `stream`.
    """
    if msg is None:
        return None
    code = _ansi_color_table.get(color, None)
    if code is None:
        abort('Unsupported color: ' + color + '.\nSupported colors are: ' + ', '.join(_ansi_color_table.keys()))
    if bright:
        code += ';1'
    color_on = '\033[' + code + 'm'
    if not msg.startswith(color_on):
        isUnix = sys.platform.startswith('linux') or sys.platform in ['darwin', 'freebsd']
        if isUnix and hasattr(stream, 'isatty') and stream.isatty():
            return color_on + msg + '\033[0m'
    return msg

def warn(msg, context=None):
    if _opts.warn and not _opts.quiet:
        if context is not None:
            if callable(context):
                contextMsg = context()
            elif hasattr(context, '__abort_context__'):
                contextMsg = context.__abort_context__()
            else:
                contextMsg = str(context)
            msg = contextMsg + ":\n" + msg
        print(colorize('WARNING: ' + msg, color='magenta', bright=True, stream=sys.stderr), file=sys.stderr)

def abort(codeOrMessage, context=None, killsig=signal.SIGTERM):
    """
    Aborts the program with a SystemExit exception.
    If `codeOrMessage` is a plain integer, it specifies the system exit status;
    if it is None, the exit status is zero; if it has another type (such as a string),
    the object's value is printed and the exit status is 1.

    The `context` argument can provide extra context for an error message.
    If `context` is callable, it is called and the returned value is printed.
    If `context` defines a __abort_context__ method, the latter is called and
    its return value is printed. Otherwise str(context) is printed.
    """
    if threading.current_thread() is threading.main_thread():
        if is_continuous_integration() or _opts and hasattr(_opts, 'killwithsigquit') and _opts.killwithsigquit:
            logv('sending SIGQUIT to subprocesses on abort')
            _send_sigquit()

        for p, args in _currentSubprocesses:
            if _is_process_alive(p):
                if is_windows():
                    p.terminate()
                else:
                    _kill_process(p.pid, killsig)
                time.sleep(0.1)
            if _is_process_alive(p):
                try:
                    if is_windows():
                        p.terminate()
                    else:
                        _kill_process(p.pid, signal.SIGKILL)
                except BaseException as e:
                    if _is_process_alive(p):
                        log_error(f"error while killing subprocess {p.pid} \"{' '.join(args)}\": {e}")

    sys.stdout.flush()
    if is_continuous_integration() or (_opts and hasattr(_opts, 'verbose') and _opts.verbose):
        import traceback
        traceback.print_stack()
    if context is not None:
        if callable(context):
            contextMsg = context()
        elif hasattr(context, '__abort_context__'):
            contextMsg = context.__abort_context__()
        else:
            contextMsg = str(context)
    else:
        contextMsg = ""

    if isinstance(codeOrMessage, int):
        # Log the context separately so that SystemExit
        # communicates the intended exit status
        error_message = contextMsg
        error_code = codeOrMessage
    elif contextMsg:
        error_message = contextMsg + ":\n" + codeOrMessage
        error_code = 1
    else:
        error_message = codeOrMessage
        error_code = 1
    log_error(error_message)
    raise SystemExit(error_code)

def abort_or_warn(message, should_abort, context=None):
    if should_abort:
        abort(message, context)
    else:
        warn(message, context)

def nyi(name, obj):
    abort(f'{name} is not implemented for {obj.__class__.__name__}')
    raise NotImplementedError()
