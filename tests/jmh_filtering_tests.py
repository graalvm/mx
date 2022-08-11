from os.path import dirname, realpath, sep
import os
import re
import sys

file_dir = dirname(realpath(__file__))
sys.path.append(file_dir + sep + "..")

import mx

# Test basic JMH benchmark listing functionality. This exercises JMH command line parsing via the FilterJMHFlags Java
# helper class.
def checkListingExclusions(exclusions, expected):
    parent_dir = os.path.normpath(file_dir + sep + "..")
    out = mx.TeeOutputCapture(mx.OutputCapture())
    env = os.environ.copy()
    env["MX_PRIMARY_SUITE_PATH"] = parent_dir
    mx_bin = os.path.normpath(parent_dir + sep + "mx")
    # we're parsing stdout, so we need to make sure that trackers are disabled such that no extra output is generated
    mx.run([mx_bin, 'benchmark', 'jmh-dist:MX_MICRO_BENCHMARKS', '--tracker', 'none', '--', '--', '-l'] + exclusions,
            out=out, env=env, cwd=parent_dir)

    # Extract benchmark names from the output.
    benchmarks = []
    start = re.compile("Benchmarks:")
    end = re.compile(r"\d+ benchmark data points dumped")
    collecting = False
    for line in out.underlying.data.splitlines():
        if start.match(line):
            collecting = True
        elif end.match(line):
            collecting = False
            break
        elif collecting:
            # Collect unqualified name.
            benchmarks.append(line.split('.')[-1])

    if set(benchmarks) != set(expected):
        mx.abort(f"Filtering benchmarks with {exclusions} gave {benchmarks}, expected {expected}")

# Ensure attribute existence for test
setattr(mx._opts, "verbose", False)
setattr(mx._opts, "warn", True)
setattr(mx._opts, "quiet", False)
setattr(mx._opts, "exec_log", None)
setattr(mx._opts, "ptimeout", 0)

checkListingExclusions([], ["testJMH", "otherTest"])
checkListingExclusions(["-e", "test"], ["otherTest"])
checkListingExclusions(["-e", "erT"], ["testJMH"])
checkListingExclusions(["-e", "[tT]"], [])
