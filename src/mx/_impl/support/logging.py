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

from __future__ import annotations

__all__ = [
    "abort",
    "abort_or_warn",
    "log",
    "logv",
    "logvv",
    "log_error",
    "log_deprecation",
    "nyi",
    "colorize",
    "warn",
    "getLogTask",
    "setLogTask",
]

import sys, signal, threading
import traceback
from typing import Any, NoReturn, Optional

from .options import _opts, _opts_parsed_deferrables


# https://en.wikipedia.org/wiki/ANSI_escape_code#Colors
_ansi_color_table = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}

_logTask = threading.local()


def setLogTask(task):
    _logTask.task = task


def getLogTask():
    if not hasattr(_logTask, "task"):
        return None
    return _logTask.task


def _check_stdout_encoding():
    # Importing here to avoid broken circular import
    from .envvars import env_var_to_bool
    from .system import is_continuous_integration

    if not env_var_to_bool("MX_CHECK_IOENCODING", "1"):
        return

    encoding = sys.stdout.encoding

    if "utf" not in encoding:
        msg = (
            "Python's stdout does not use a unicode encoding.\n"
            "This may cause encoding errors when printing special characters.\n"
            "Please set up your system or console to use a unicode encoding.\n"
            "When piping mx output, you can force UTF-8 encoding with the environment variable PYTHONIOENCODING=utf-8\n"
            "This check can be disabled by setting MX_CHECK_IOENCODING=0 environment variable"
        )
        if is_continuous_integration():
            abort(msg)
        else:
            warn(msg)


def _print_impl(msg: Optional[str] = None, end: Optional[str] = "\n", file=sys.stdout):
    try:
        print(msg, end=end, file=file)
    except UnicodeEncodeError as e:
        # In case any text is printed that can't be encoded (e.g. if output console does not use a unicode encoding),
        # print an error message and try to print text as good as possible.

        error_handler = "backslashreplace"
        offending_str = (
            e.object[e.start : e.end].encode(e.encoding, errors=error_handler).decode(e.encoding, errors="ignore")
        )

        # Not using our log functions here to avoid infinite recursion in case these calls cause unicode errors
        def print_err(err_msg: str):
            print(colorize(err_msg, color="red"), file=sys.stderr)

        print_err(f"[ENCODING ERROR] {e}. Encoding: {e.encoding}. Offending characters: '{offending_str}'")

        if "verbose" in _opts and _opts.verbose:
            traceback.print_stack()
        else:
            print_err("Turn on verbose mode (-v) to see the stack trace")

        print_err(f"Printing text with '{error_handler}' error handler:")

        # Encode and decode with the target encoding to get a string that can be safely printed
        print(
            msg.encode(e.encoding, errors=error_handler).decode(e.encoding, errors="ignore"),
            end=end,
            file=file,
        )


def log(msg: Optional[str] = None, end: Optional[str] = "\n", file=sys.stdout):
    """
    Write a message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    task = getLogTask()
    if task is not None:
        task.log(msg)
        return
    if vars(_opts).get("quiet"):
        return
    if msg is None:
        _print_impl(end=end, file=file)
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
        _print_impl(str(msg), end=end, file=file)


def logv(msg: Optional[str] = None, end="\n") -> None:
    if vars(_opts).get("verbose") is None:

        def _deferrable():
            logv(msg, end=end)

        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.verbose:
        log(msg, end=end)


def logvv(msg: Optional[str] = None, end="\n") -> None:
    if vars(_opts).get("very_verbose") is None:

        def _deferrable():
            logvv(msg, end=end)

        _opts_parsed_deferrables.append(_deferrable)
        return

    if _opts.very_verbose:
        log(msg, end=end)


def log_error(msg: Optional[str] = None, end="\n") -> None:
    """
    Write an error message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if msg is None:
        _print_impl(file=sys.stderr, end=end)
    else:
        _print_impl(colorize(str(msg), stream=sys.stderr), file=sys.stderr, end=end)


def log_deprecation(msg: Optional[str] = None) -> None:
    """
    Write an deprecation warning to the console.
    """
    if msg is None:
        _print_impl(file=sys.stderr)
    else:
        _print_impl(colorize(str(f"[MX DEPRECATED] {msg}"), color="yellow", stream=sys.stderr), file=sys.stderr)


def colorize(msg: Optional[str], color="red", bright=True, stream=sys.stderr) -> Optional[str]:
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
        return abort("Unsupported color: " + color + ".\nSupported colors are: " + ", ".join(_ansi_color_table.keys()))
    if bright:
        code += ";1"
    color_on = "\033[" + code + "m"
    if not msg.startswith(color_on):
        isUnix = sys.platform.startswith("linux") or sys.platform in ["darwin", "freebsd"]
        if isUnix and hasattr(stream, "isatty") and stream.isatty():
            return color_on + msg + "\033[0m"
    return msg


def warn(msg: str, context=None) -> None:
    if _opts.warn and not _opts.quiet:
        if context is not None:
            if callable(context):
                contextMsg = context()
            elif hasattr(context, "__abort_context__"):
                contextMsg = context.__abort_context__()
            else:
                contextMsg = str(context)
            msg = contextMsg + ":\n" + msg
        msg = colorize("WARNING: " + msg, color="magenta", bright=True, stream=sys.stderr)
        task = getLogTask()
        if task is None:
            _print_impl(msg, file=sys.stderr)
        else:
            task.log(msg)


def abort(codeOrMessage: str | int, context=None, killsig=signal.SIGTERM) -> NoReturn:
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
    from .system import is_continuous_integration
    from .processes import terminate_subprocesses

    if threading.current_thread() is threading.main_thread():
        if is_continuous_integration() or _opts and hasattr(_opts, "killwithsigquit") and _opts.killwithsigquit:
            from ..mx import _send_sigquit

            logv("sending SIGQUIT to subprocesses on abort")
            _send_sigquit()

        terminate_subprocesses(killsig)

    sys.stdout.flush()
    if is_continuous_integration() or (_opts and hasattr(_opts, "verbose") and _opts.verbose):
        traceback.print_stack()
    if context is not None:
        if callable(context):
            contextMsg = context()
        elif hasattr(context, "__abort_context__"):
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

    t = getLogTask()
    if t is not None:
        if error_message:
            t.log(error_message)
        t.abort(error_code)
    else:
        log_error(error_message)
        raise SystemExit(error_code)


def abort_or_warn(message: str, should_abort: bool, context=None) -> Optional[NoReturn]:
    if should_abort:
        abort(message, context)
    else:
        warn(message, context)


def nyi(name: str, obj: Any) -> NoReturn:
    """Throw a not yet implemented error."""
    abort(f"{name} is not implemented for {obj.__class__.__name__}")
    raise NotImplementedError()
