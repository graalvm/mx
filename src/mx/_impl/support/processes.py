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

# Makes the current subprocess accessible to the abort() function
# This is a list of tuples of the subprocess.Popen or
# multiprocessing.Process object and args.
_currentSubprocesses = []

ERROR_TIMEOUT = 0x700000000 # not 32 bits

def _is_process_alive(p):
    if isinstance(p, subprocess.Popen):
        return p.poll() is None
    assert isinstance(p, multiprocessing.Process), p
    return p.is_alive()

def _check_output_str(*args, **kwargs):
    try:
        return subprocess.check_output(*args, **kwargs).decode()
    except subprocess.CalledProcessError as e:
        if e.output:
            e.output = e.output.decode()
        if hasattr(e, 'stderr') and e.stderr:
            e.stderr = e.stderr.decode()
        raise e

def _kill_process(pid, sig):
    """
    Sends the signal `sig` to the process identified by `pid`. If `pid` is a process group
    leader, then signal is sent to the process group id.
    """
    try:
        logvv(f'[{os.getpid()} sending {sig} to {pid}]')
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
        return True
    except Exception as e:  # pylint: disable=broad-except
        log('Error killing subprocess ' + str(pid) + ': ' + str(e))
        return False

def _waitWithTimeout(process, cmd_line, timeout, nonZeroIsFatal=True, on_timeout=None):
    try:
        return process.wait(timeout)
    except subprocess.TimeoutExpired:
        if on_timeout:
            on_timeout(process)
        log_error(f'Process timed out after {timeout} seconds: {cmd_line}')
        process.kill()
        return ERROR_TIMEOUT

def _addSubprocess(p, args):
    entry = (p, args)
    logvv(f'[{os.getpid()}: started subprocess {p.pid}: {args}]')
    _currentSubprocesses.append(entry)
    return entry

def _removeSubprocess(entry):
    if entry and entry in _currentSubprocesses:
        try:
            _currentSubprocesses.remove(entry)
        except:
            pass

def waitOn(p):
    if is_windows():
        # on windows use a poll loop, otherwise signal does not get handled
        retcode = None
        while retcode is None:
            retcode = p.poll()
            time.sleep(0.05)
    else:
        retcode = p.wait()
    return retcode

