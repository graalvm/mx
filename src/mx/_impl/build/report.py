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
import os
import time

from .. import mx

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
        .header dt { font-weight: bold; }
        .success:before { content: "success"; color: green; }
        .failed:before { content: "failed"; color: red; }
        .skipped:before { content: "skipped"; margin-right: 2em; color: blue; }
        .log:before { content: "build log:"; }
        .log pre { border: 1px inset; padding: 5px; max-height: 350px; overflow: auto; }
    </style>
    ''')

class BuildReport:
    def __init__(self, cmd_args):
        self.tasks = []
        self.properties = {}
        if cmd_args:
            self.properties['arguments'] = " ".join(cmd_args)

    def set_tasks(self, tasks):
        self.tasks = tasks

    def add_info(self, key, value):
        self.properties[key] = value

    def _write_header(self, f):
        f.write('<h1>mx build report</h1>\n<dl class="header">\n')
        for k in self.properties:
            f.write(f"    <dt>{k}</dt>\n")
            v = self.properties[k]
            if isinstance(v, list):
                f.write("        <dd>\n")
                for i in v:
                    f.write(f"            {html.escape(str(i))}<br/>\n")
                f.write("        </dd>\n")
            else:
                f.write(f"        <dd>{html.escape(str(v))}</dd>\n")
        f.write('</dl>\n')

    def _write_report(self, filename):
        allSkipped = True
        for t in self.tasks:
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
            self._write_header(f)
            for t in self.tasks:
                if t.status is not None:
                    # only report on tasks that were started
                    write_task_report(f, t)
            write_style(f)
            f.write('</body>\n')
            f.write('</html>\n')
        mx.log(f"mx build log written to {filename}")

    def _print_failed(self):
        failed = 0
        for t in self.tasks:
            if t.status == 'failed':
                failed += 1
                mx.log_error(f'{t} failed')
                for l in t._log.lines:
                    mx.log(l)
        if failed > 0:
            mx.abort(f'{failed} build tasks failed')

    def __enter__(self):
        self.properties['started'] = time.strftime("%Y-%m-%d %H:%M:%S")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.properties['finished'] = time.strftime("%Y-%m-%d %H:%M:%S")

        reportDir = mx.primary_suite().get_output_root(jdkDependent=False)
        mx.ensure_dir_exists(reportDir)
        base_name = time.strftime("buildlog-%Y%m%d-%H%M%S")
        reportFile = os.path.join(reportDir, base_name + ".html")
        reportIdx = 0
        while os.path.exists(reportFile):
            reportIdx += 1
            reportFile = os.path.join(reportDir, f'{base_name}_{reportIdx}.html')
        self._write_report(reportFile)

        self._print_failed()
