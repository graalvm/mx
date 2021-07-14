#
# ----------------------------------------------------------------------------------------------------

# Copyright (c) 2021, Oracle and/or its affiliates. All rights reserved.
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

from __future__ import print_function

import collections
from xml.etree import ElementTree

import mx
from argparse import ArgumentParser, RawTextHelpFormatter, ONE_OR_MORE


def unique_prefix(key, choices):
    matches = [x for x in choices if x.startswith(key)]
    return matches[0] if len(matches) == 1 else key


class HotSpotNMethod:
    def __init__(self, compile_id, is_osr, name, installed_code_name, entry_pc, level, stamp):
        self.compile_id = compile_id
        self.is_osr = is_osr
        self.method = HotSpotNMethod.parse_method(name)
        self.installed_code_name = installed_code_name
        self.entry_pc = entry_pc
        self.level = level
        self.stamp = stamp

    def __repr__(self):
        return '{}: {}{}'.format(self.get_compile_id(),
                                 '' if not self.installed_code_name else '\"{}\" '.format(self.installed_code_name),
                                 self.format_name())

    def format_name(self, with_arguments=True):
        return self.method.format_name(with_arguments=with_arguments)

    def get_compile_id(self):
        return str(self.compile_id) + ('%' if self.is_osr else '')

    @staticmethod
    def parse_method(name):
        # decode any unicode escapes
        name = str(bytes(name, encoding='utf-8'), encoding='unicode_escape')
        parts = name.split(' ')
        from mx_proftool import Method
        return Method('L' + parts[0] + ';', parts[1], parts[2], None, None)


def find_nmethods(fp):
    """
    Collect the compiled method information from the HotSpot LogCompilation output.

    :rtype: list[HotSpotNMethod]
    """
    return collect_nmethods(ElementTree.parse(fp))


def collect_nmethods(tree):
    """
    Collect the compiled method information from the HotSpot LogCompilation output.

    :rtype: list[HotSpotNMethod]
    """
    nmethods = []
    for x in tree.getroot().iter('nmethod'):
        compile_id = int(x.get('compile_id'))
        level = int(x.get('level', 4))
        entry = int(x.get('entry'), 16)
        compile_kind = x.get('compile_kind')
        name = x.get('method')
        stamp = float(x.get('stamp'))
        installed_code_name = x.get('jvmci_mirror_name')
        nmethods.append(HotSpotNMethod(compile_id, compile_kind == 'osr', name, installed_code_name, entry, level, stamp))
    return nmethods


def open_log_compilation(filename):
    """
    Open a proftool experiment containing a LogCompilation file or
    open the file directly.
    """
    from mx_proftool import ExperimentFiles
    experiment = ExperimentFiles.open_experiment(filename)
    if experiment:
        if experiment.has_log_compilation():
            return experiment.open_log_compilation_file()
        mx.abort('Experiment {} is missing log compilation output'.format(filename))
    return open(filename)


@mx.command('mx', 'logc', '[options]')
@mx.suite_context_free
def logc(args):
    parser = ArgumentParser(
        prog="mx logc",
        description='Parse a HotSpot -XX:+LogCompilation file and report useful information.\n'
                    'Can open a LogCompilation file embedded in a proftool experiment.',
        formatter_class=RawTextHelpFormatter)
    diff_choices = ['print', 'traps', 'summary']
    parser.add_argument('--action', '-a', default='print', choices=diff_choices,
                        type=lambda s: unique_prefix(s, diff_choices), help='')
    parser.add_argument('files', help='List of files', nargs=ONE_OR_MORE)
    args = parser.parse_args(args)

    for filename in args.files:
        with open_log_compilation(filename) as handle:
            if len(args.files) > 1:
                print(filename)
            tree = ElementTree.parse(handle)
            if args.action == 'print':
                print_compilation(tree)
            elif args.action == 'summary':
                print_compile_queue_statistics(tree)
                print('')
                print_uncommon_trap_statistics(tree)
            elif args.action == 'traps':
                print_uncommon_traps(compute_uncommon_traps(tree))
            else:
                mx.abort('Unknown action: {}'.format(args.action))


def print_compilation(tree):
    tasks = sorted(tree.getroot().iter('task'), key=lambda x: float(x.get('stamp')))
    for task in tasks:
        done = task.find('task_done')
        if done.get('success') == '1':
            print_task(task)
        else:
            failure = task.find('failure')
            reason = failure.get('reason')
            if reason != 'stale task':
                print_task(task, reason)


def print_compile_queue_statistics(tree):
    queued_total = [0, 0, 0, 0, 0]
    dequeued_total = [0, 0, 0, 0, 0]
    queued_max = [0, 0, 0, 0, 0]
    demotions = 0
    dequeued = 0
    tasks = {}
    for x in tree.getroot().iter():
        if x.tag == 'task_queued' or x.tag == 'task_dequeued' or x.tag == 'nmethod':
            compile_id = int(x.get('compile_id'))
            level = int(x.get('level', 4))
            if level == 0:
                continue
            if x.tag == 'task_dequeued':
                dequeued = dequeued + 1
                dequeued_total[level] = dequeued_total[level] + 1
            if x.tag == 'task_queued':
                tasks[compile_id] = level
            else:
                starting_level = tasks[compile_id]
                if starting_level != level:
                    queued_total[starting_level] = queued_total[starting_level] - 1
                    queued_total[level] = queued_total[level] + 1
                    demotions = demotions + 1
            delta = 1 if x.tag == 'task_queued' else -1
            queued_total[level] = queued_total[level] + delta
            queued_max[level] = max(queued_total[level], queued_max[level])

    bytes_per_level = [0, 0, 0, 0, 0]
    compiles_per_level = [0, 0, 0, 0, 0]
    seconds_per_level = [0, 0, 0, 0, 0]
    for task in tree.getroot().iter('task'):
        level = int(task.get('level', 4))
        task_done = next(task.iter('task_done'))
        compiled_bytes = int(task.get('bytes'))
        inlined_bytes = int(task_done.get('inlined_bytes', 0))
        start = float(task.get('stamp'))
        end = float(task_done.get('stamp'))
        total_bytes = compiled_bytes + inlined_bytes
        elapsed = end - start
        if elapsed == 0:
            elapsed = 0.0001
        bytes_per_level[level] = bytes_per_level[level] + total_bytes
        seconds_per_level[level] = seconds_per_level[level] + elapsed
        if int(task_done.get('success')) == 1:
            compiles_per_level[level] = compiles_per_level[level] + 1

    titles = ('level', 'compiles', 'total bytes', 'total time', 'bytes per second', 'max queued', 'dequeued')
    lines = []
    for level in range(1, 5):
        rate = 0
        if seconds_per_level[level] > 0:
            rate = int(bytes_per_level[level] / seconds_per_level[level])
        lines.append((level, compiles_per_level[level], bytes_per_level[level],
                      '{:.3f}'.format(seconds_per_level[level]), rate, queued_max[level], dequeued_total[level]))

    # compute column widths for output
    widths = [len(x) for x in titles]
    for line in lines:
        w2 = [len(str(x)) for x in line]
        widths = [max(x) for x in zip(widths, w2)]

    print('Compile queue statistics:')
    layout = '   '.join(['{:>' + str(x) + '}' for x in widths])
    print(layout.format(*titles))
    for line in lines:
        print(layout.format(*line))
    print('{} dequeued {} demoted'.format(dequeued, demotions))


def print_task(task, reason=None):
    osr_bci = task.get('osr_bci')
    osr_tag = '%' if osr_bci else ''
    print('{} {}{} {} {}{}{}'.format(task.get('stamp'), task.get('compile_id'), osr_tag, task.get('level'),
                                     task.get('method'), '' if not osr_bci else ' @' + osr_bci,
                                     '' if not reason else ' ' + reason))


def print_make_not(event, tasks):
    task = tasks[event.get('compile_id')]
    osr_bci = task.get('osr_bci')
    osr_tag = '%' if osr_bci else ''
    print('{} {}{} {} {}{} {}'.format(event.get('stamp'), task.get('compile_id'), osr_tag, task.get('level'),
                                      task.get('method'), '' if not osr_bci else ' @' + osr_bci, event.tag))


def print_event(event, tasks):
    if event.tag == 'task':
        print_task(event)
    elif event.tag == 'make_not_entrant' or event.tag == 'make_not_compilable':
        print_make_not(event, tasks)


def first_element(element, tag):
    return next(element.iter(tag))


def compute_uncommon_traps(tree):
    """
    Group uncommon traps by the reason, action and the frame state at the deopt point.
    """
    nmethods = collect_nmethods(tree)
    nmethods_by_id = {}
    for nmethod in nmethods:
        nmethods_by_id[nmethod.compile_id] = nmethod
    grouped = {}
    for trap in tree.getroot().iter('uncommon_trap'):
        all_jvms = list(trap.iter('jvms'))
        all_jvms.reverse()

        if len(all_jvms) == 0:
            continue
        method = first_element(trap, 'jvms').get('method')
        reason = trap.get('reason')
        action = trap.get('action')
        jvms = tuple([HotSpotNMethod.parse_method(jvms.get('method')).format_name() + ' @ ' + jvms.get('bci') for jvms in all_jvms])
        key = (method, reason, action, jvms)
        nmethod = nmethods_by_id[int(trap.get('compile_id'))]
        if key in grouped:
            grouped[key].append(nmethod)
        else:
            grouped[key] = [key, nmethod]
    return sorted([x for x in grouped.values() if len(x) > 2], key=len, reverse=True)


def print_uncommon_traps(traps):
    for trap in traps:
        method, reason, action, jvms = trap[0]
        compiles = [str(r) for r in trap[1:]]
        print('Method: {}\n  Reason: {} Action: {}'.format(HotSpotNMethod.parse_method(method).format_name(), reason, action))
        print('  Traps   Compilation')
        for o in sorted(collections.Counter(compiles).items(), key=lambda x: x[1], reverse=True):
            print('    {:3}   {}'.format(o[1], o[0]))
        print('  State at trap:')
        print('    {}'.format('\n    '.join(jvms)))
        print()


def print_uncommon_trap_statistics(tree):
    traps = compute_uncommon_traps(tree)
    total = 0
    unique = 0
    count_by_reason_action = {}
    for trap in traps:
        _, reason, action, _ = trap[0]
        ids = [x.compile_id for x in trap[1:]]
        key = (reason, action)
        current = count_by_reason_action.setdefault(key, 0)
        count_by_reason_action[key] = current + len(ids)
        total += len(ids)
        unique += len(list(set(ids)))
    print('Uncommon trap statistics:')
    print('  Total uncommon traps taken: {}'.format(total))
    print('  Unique traps: {}'.format(unique))
    print('  Counts by trap kind:')
    for key in count_by_reason_action:
        reason, action = key
        print('    {}/{}: {}'.format(reason, action, count_by_reason_action[key]))
