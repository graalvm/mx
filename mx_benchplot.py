#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, Oracle and/or its affiliates. All rights reserved.
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

import json
from argparse import ArgumentParser, REMAINDER
from argparse import RawTextHelpFormatter
import os.path
import sys

import mx


def suite_context_free(func):
    """
    Decorator for commands that don't need a primary suite.
    """
    mx._suite_context_free.append(func.__name__)
    return func


def unique_prefix(s, choices):
    r = [x for x in choices if x.startswith(s)]
    return r[0] if len(r) == 1 else s

@suite_context_free
def benchtable(args):
    parser = ArgumentParser(
        prog="mx benchtable",
        description=
    """
Generate a table of benchmark results for a set of JSON benchmark
result files.  By default this emits a text formatted table with a
colum for each result and a column reporting the percentage change
relative to the first set of results.  All files must come from the same
benchmark suite.
""",
        formatter_class=RawTextHelpFormatter)
    parser.add_argument('--format', action='store', choices=['text', 'csv', 'jira', 'markdown'], default='text', help='Set the output format. (Default: text)')
    diff_choices = ['percent', 'absolute', 'none']
    parser.add_argument('--diff', default='relative', choices=diff_choices, type=lambda s: unique_prefix(s, diff_choices),
                        help='Add a column reporting the difference relative the first score. (Default: percent)')
    parser.add_argument('-f', '--file', default=None, help='Generate the table into a file.')
    parser.add_argument('--last-n', action='store', default=1, type=int,
                        help="""Only report last n scores.  By default only report the last score.
Negative numbers can be used to select the first scores instead""")
    parser.add_argument('--variance', action='store_true', help='Report the percentage variance of the scores.')
    parser.add_argument('-n', '--names', help='A list of comma separate names for each file.  \n' +
                        'It must have the same number of entries as the files.', type=lambda s: s.split(','))

    parser.add_argument('files', help='List of files', nargs=REMAINDER)
    args = parser.parse_args(args)

    if args.diff == 'none':
        args.diff = None

    benchmarks, results, _ = extract_results(args.files, args.names, args.last_n)

    score_key = 'score'
    variance_key = 'variance'
    if args.last_n:
        score_key = 'trimmed_score'
        variance_key = 'trimmed_variance'

    handle = open(args.file, 'w') if args.file else sys.stdout

    # build a collection of rows and compute padding required to align them
    table = []
    widths = []
    specifiers = []
    headers = []
    for benchmark in benchmarks:
        row = [benchmark]
        specifiers = ['s']
        headers = ['Benchmark']
        first = True
        for result in results:
            score = 0.0001
            variance = 0.0001
            scale = 1
            if result.get(benchmark):
                score = result[benchmark][score_key]
                variance = result[benchmark][variance_key]
                if not result[benchmark]['higher']:
                    scale = -1
            row.append(score)
            specifiers.append('.2f')
            headers.append(result[benchmark]['name'])
            if args.variance:
                row.append('%.2f%%' % variance)
                specifiers.append('s')
                headers.append('Variance')
            if not first and args.diff:
                if args.diff == 'percent':
                    row.append('%.2f%%' % ((score - row[1]) * 100.0 * scale / row[1]))
                    specifiers.append('s')
                    headers.append('Change')
                elif args.diff == 'absolute':
                    row.append('%.2f' % ((score - row[1]) * scale))
                    specifiers.append('s')
                    headers.append('Delta')
            first = False

        table.append(row)
        w = [max(len(h), len(('%' + spec) % (x))) for spec, x, h in zip(specifiers, row, headers)]
        if len(widths) == 0:
            widths = w
        else:
            widths = map(max, widths, w)

    if args.format == 'text':
        handle.write('  '.join(['%' + str(w) + 's' for w in  widths]) % tuple(headers) + '\n')
        format_string = '  '.join(['%' + str(w) + s for s, w in zip(specifiers, widths)])
        for row in table:
            handle.write(format_string % tuple(row) + '\n')
    else:
        header_sep = None
        row_sep = None

        header_terminator = ''
        row_terminator = ''

        header_separator = None

        if args.format == 'jira':
            header_sep = '||'
            header_terminator = '||'
            row_sep = '|'
            row_terminator = '|'
        elif args.format == 'csv':
            header_sep = ','
            row_sep = ','
        elif args.format == 'markdown':
            header_sep = '|'
            row_sep = '|'
            header_terminator = '|'
            row_terminator = '|'
            # Bitbucket server doesn't respect the alignment colons and
            # not all markdown processors support tables.
            header_separator = '---:'
        else:
            mx.abort('Unhandled format: ' + args.format)

        handle.write(header_terminator + header_sep.join(headers) + header_terminator + '\n')
        if header_separator:
            handle.write(header_terminator + header_sep.join([header_separator for h in headers]) + header_terminator + '\n')
        formats = ['%' + str(w) + s for s, w in zip(specifiers, widths)]
        for row in table:
            handle.write(row_terminator + row_sep.join([(f % r).strip() for r, f in zip(row, formats)]) + row_terminator + '\n')

    if handle is not sys.stdout:
        handle.close()


@suite_context_free
def benchplot(args):
    parser = ArgumentParser(
        prog="mx benchplot",
        description="""
Generate a plot of benchmark results for a set of JSON benchmark
result files using the Python package matplotlib.  By default this
produces a bar chart comparing the final score in each result file.
The --warmup option can be used to graph the individual scores in
sequence.  All files must come from the same benchmark suite.
""",
        formatter_class=RawTextHelpFormatter)
    parser.add_argument('-w', '--warmup', action='store_true', help='Plot a warmup graph')
    parser.add_argument('-f', '--file', default=None,
                        help='Generate the graph into a file.  The extension will determine the format, which must be .png, .svg or .pdf.')
    parser.add_argument('--last-n', action='store', type=int,
                        help="""Only report last n scores.  By default only plot the last score in the bar graph.
Negative numbers can be used to select the first scores instead""")
    parser.add_argument('-n', '--names', help='Provide a list of names for the plot files', type=lambda s: s.split(','))
    parser.add_argument('-c', '--colors', help='Provide alternate colors for the results', type=lambda s: s.split(','))
    parser.add_argument('files', help='List of files', nargs=REMAINDER)
    args = parser.parse_args(args)

    if not args.warmup and not args.last_n:
        # only report the final score in bar graph.
        args.last_n = 1

    try:
        import matplotlib.pyplot as plt
        color_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']

        benchmarks, results, names = extract_results(args.files, args.names, args.last_n)
        score_key = 'score'
        scores_key = 'scores'
        if args.last_n:
            score_key = 'trimmed_score'
            scores_key = 'trimmed_scores'

        if not args.colors:
            args.colors = color_cycle[0:len(names)]

        if args.warmup:
            index = 1
            rows = 1
            cols = 1
            if len(benchmarks) > 1:
                cols = 2
                rows = (len(benchmarks) + cols - 1) / cols
            plt.figure(figsize=(8.5, 11), dpi=100)
            for b in benchmarks:
                ax = plt.subplot(rows, cols, index)
                plt.title(b)
                for r in results:
                    scores = r[b][scores_key]
                    plt.plot(scores, label=r[b]['name'])
                handles, labels = ax.get_legend_handles_labels()
                ax.legend(handles, labels, loc='upper right', fontsize='small', ncol=2)
                ax.set_ylim(ymin=0)
                index = index + 1
        else:
            _, ax = plt.subplots(figsize=(11, 8.5), dpi=100)
            x = 0
            bar_width = 0.25
            spacing = 0.5
            column_width = bar_width * len(names) + spacing
            column_center = bar_width * ((len(names) - 1) / 2)

            group = 0
            rects = []
            xticks = []
            for name, color in zip(names, args.colors):
                scores = []
                xs = []
                column = 0
                xticks = []
                for b in benchmarks:
                    for r in results:
                        if r[b]['name'] == name:
                            if r[b].get(score_key):
                                scores.append(r[b][score_key])
                                xs.append(x + column * column_width + group * bar_width)
                            xticks.append(column * column_width + column_center)
                            column = column + 1
                rects.append(ax.bar(xs, scores, width=bar_width, color=color))
                group = group + 1
            ax.legend(rects, names)
            ax.set_xticks(xticks)
            ax.set_xticklabels(benchmarks)

        plt.tight_layout()
        if args.file:
            plt.savefig(args.file)
        else:
            plt.show()

    except ImportError as e:
        print e
        mx.abort('matplotlib must be available to use benchplot.  Install it using pip')


def extract_results(files, names, last_n=None):
    if names:
        if len(names) != len(files):
            mx.abort('Wrong number of names specified: {} files but {} names.'.format(len(files), len(names)))
    else:
        names = [os.path.splitext(os.path.basename(x))[0] for x in files]
        if len(names) != len(set(names)):
            mx.abort('Base file names are not unique.  Specify names using --names')

    results = []
    benchmarks = []
    bench_suite = None
    for filename, name in zip(files, names):
        result = {}
        results.append(result)
        with open(filename) as fp:
            for entry in json.load(fp)['queries']:
                benchmark = entry['benchmark']
                if benchmark not in benchmarks:
                    benchmarks.append(benchmark)
                if bench_suite == None:
                    bench_suite = entry['bench-suite']
                else:
                    if bench_suite != entry['bench-suite']:
                        mx.abort("File '{}' contains bench-suite '{}' but expected '{}'.".format(filename, entry['bench-suite'], bench_suite))
                score = entry['metric.value']
                scores = result.get(benchmark)
                if scores:
                    scores['scores'].append(score)
                else:
                    higher = entry['metric.better'] == 'higher'
                    result[benchmark] = {'scores': [score], 'higher': higher, 'name': name}

        for _, entry in result.iteritems():
            if last_n and len(entry['scores']) > abs(last_n):
                if last_n < 0:
                    entry['trimmed_scores'] = entry['scores'][:-last_n]
                else:
                    entry['trimmed_scores'] = entry['scores'][-last_n:]
                entry['trimmed_count'] = len(entry['trimmed_scores'])
                entry['trimmed_score'] = sum(entry['trimmed_scores']) / len(entry['trimmed_scores'])

            entry['count'] = len(entry['scores'])
            entry['score'] = sum(entry['scores']) / len(entry['scores'])

        # Compute a variance value.  This is a percentage variance relative to the average score
        # which is easier to interpret than a raw number.
        for _, entry in result.iteritems():
            variance = 0
            for score in entry['scores']:
                variance = variance + (score - entry['score']) * (score - entry['score'])
            entry['variance'] = ((variance / entry['count']) / entry['score'])
            if entry.get('trimmed_scores'):
                variance = 0
                for score in entry['trimmed_scores']:
                    variance = variance + (score - entry['trimmed_score']) * (score - entry['trimmed_score'])
                entry['trimmed_variance'] = ((variance / entry['trimmed_count']) / entry['trimmed_score'])

    return benchmarks, results, names
