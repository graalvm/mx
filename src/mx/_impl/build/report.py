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

import html

from ..support.logging import log

def write_task_report(f, task):
    f.write('\n<div class="task">\n')
    f.write(f'    <h2>{task.name}</h2>\n')
    f.write(f'    <p class="result {task.status}">{task.statusInfo}</p>\n')
    l = str(task._log).strip()
    if l:
        f.write('        <span class="log"><pre>\n')
        f.write(html.escape(l))
        f.write('\n        </pre></span>\n')
    f.write('</div>\n')

def write_style(f):
    f.write('''
    <style>
        .success:before { content: "success"; color: green; }
        .failed:before { content: "failed"; color: red; }
        .skipped:before { content: "skipped"; margin-right: 2em; color: blue; }
        .log:before { content: "build log:"; }
        .log pre { border: 1px inset; padding: 5px; max-height: 350px; overflow: auto; }
    </style>
    ''')

def write_build_report(filename, tasks):
    allSkipped = True
    for t in tasks:
        if t.status != "skipped":
            allSkipped = False
            break
    if allSkipped:
        # don't bother writing a build log if there was nothing to do
        return
    with open(filename, 'w', encoding='utf-8') as f:
        f.write('<!DOCTYPE html>\n')
        f.write('<html>\n')
        f.write('<body>\n')
        for t in tasks:
            if t.status is not None:
                # only report on tasks that were started
                write_task_report(f, t)
        write_style(f)
        f.write('</body>\n')
        f.write('</html>\n')
    log(f"mx build log written to {filename}")
