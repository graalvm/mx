#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2015, Oracle and/or its affiliates. All rights reserved.
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

import os
import shlex
import re
import urllib.parse
from os.path import join, exists, isabs, basename, dirname
from argparse import ArgumentParser

import mx
import mx_urlrewrites

def testdownstream_cli(args):
    """tests a downstream repo against the current working directory state of the primary suite

    Multiple repos can be specified with multiple instances of the -R/--repo option. The
    first specified repo is the one being tested. Further repos can be specified to either
    override where suites are cloned from or to satisfy --dynamicimports.
    """
    parser = ArgumentParser(prog='mx testdownstream')
    parser.add_argument('-R', '--repo', dest='repos', action='append', help='URL of downstream repo to clone. First specified repo is the primary repo being tested', required=True, metavar='<url>', default=[])
    parser.add_argument('--suitedir', action='store', help='relative directory of suite to test in primary repo (default: . )', default='.', metavar='<path>')
    parser.add_argument('--downstream-branch', action='store', help='comma separated names of branches to look for in downstream repo(s). '
                        'If omitted, the branches to use will be those specified by the DOWNSTREAM_BRANCH, FROM_BRANCH and TO_BRANCH environment '
                        'variables, in that order. If none of these variables are present, the current branch of the primary suite is used.', metavar='<name>')
    parser.add_argument('-C', '--mx-command', dest='mxCommands', action='append', help='arguments to an mx command run in primary repo suite (e.g., -C "-v --strict-compliance gate")', default=[], metavar='<args>')
    parser.add_argument('-E', '--encoded-space', help='character used to encode a space in an mx command argument. Each instance of this character in an argument will be replaced with a space.', metavar='<char>')

    args = parser.parse_args(args)

    mxCommands = []
    for command in [e.split() for e in args.mxCommands]:
        if args.encoded_space:
            command = [arg.replace(args.encoded_space, ' ') for arg in command]
        mxCommands.append(command)

    branch = args.downstream_branch or [mx.get_env(key, None) for key in ['DOWNSTREAM_BRANCH', 'FROM_BRANCH', 'TO_BRANCH'] if mx.get_env(key, None) is not None]
    branch = branch or None
    return testdownstream(mx.primary_suite(), args.repos, args.suitedir, mxCommands, branch)

@mx.no_suite_discovery
def testdownstream(suite, repoUrls, relTargetSuiteDir, mxCommands, branch=None):
    """
    Tests a downstream repo against the current working directory state of `suite`.

    :param mx.Suite suite: the suite to test against the downstream repo
    :param list repoUrls: URLs of downstream repos to clone, the first of which is the repo being tested
    :param str relTargetSuiteDir: directory of the downstream suite to test relative to the top level
           directory of the downstream repo being tested
    :param list mxCommands: argument lists for the mx commands run in downstream suite being tested
    :param str branch: name(s) of branch to look for in downstream repo(s)
    """

    assert len(repoUrls) > 0
    repoUrls = [mx_urlrewrites.rewriteurl(url) for url in repoUrls]

    workDir = join(suite.get_output_root(), 'testdownstream')

    # A mirror of each suites in the same repo as `suite` is created via copying
    rel_mirror = os.path.relpath(suite.dir, mx.SuiteModel.siblings_dir(suite.dir))
    in_subdir = os.sep in rel_mirror
    suites_in_repo = [suite]
    if in_subdir:
        base = os.path.dirname(suite.dir)
        for e in os.listdir(base):
            candidate = join(base, e)
            if candidate != suite.dir:
                mxDir = mx._is_suite_dir(candidate)
                if mxDir:
                    matches = [s for s in mx.suites() if s.dir == candidate]
                    if len(matches) == 0:
                        suites_in_repo.append(mx.SourceSuite(mxDir, primary=False, load=False))
                    else:
                        suites_in_repo.append(matches[0])

    if suite.vc:
        vc_metadir = mx._safe_path(mx.VC.get_vc(suite.vc_dir).metadir())
        blacklist = {
            suite.vc_dir: [join(suite.vc_dir, vc_metadir)]
        }
    else:
        blacklist = {}

    for suite_in_repo in suites_in_repo:
        output_root = mx._safe_path(suite_in_repo.get_output_root())
        blacklist.setdefault(dirname(output_root), []).append(output_root)

    def omitted_dirs(d, names):
        mx.log('Copying ' + d)
        to_omit = []
        for blacklisted_dir in blacklist.get(d, []):
            mx.log('Omitting ' + blacklisted_dir)
            to_omit.append(basename(blacklisted_dir))
        return to_omit

    if suite.vc_dir and suite.dir != suite.vc_dir:
        mirror = join(workDir, basename(suite.vc_dir))
    else:
        mirror = join(workDir, suite.name)
    if exists(mirror):
        mx.rmtree(mirror)
    mx.copytree(suite.vc_dir, mirror, ignore=omitted_dirs, symlinks=True)

    targetDir = None
    for repoUrl in repoUrls:
        # Deduce a target name from the target URL
        url = urllib.parse.urlparse(repoUrl)
        targetName = url.path
        if targetName.rfind('/') != -1:
            targetName = targetName[targetName.rfind('/') + 1:]
        if targetName.endswith('.git'):
            targetName = targetName[0:-len('.git')]

        repoWorkDir = join(workDir, targetName)
        git = mx.GitConfig()
        if exists(repoWorkDir):
            git.pull(repoWorkDir)
        else:
            git.clone(repoUrl, repoWorkDir)

        if branch is None:
            branch = []
        elif isinstance(branch, str):
            branch = [branch]
        else:
            assert isinstance(branch, list)

        # fall back to the branch of the main repo
        active_branch = git.active_branch(suite.dir, abortOnError=False)
        if active_branch:
            branch.append(active_branch)

        updated = False
        for branch_name in branch:
            if git.update_to_branch(repoWorkDir, branch_name, abortOnError=False):
                updated = True
                break
        if not updated:
            mx.warn(f"Could not update {repoWorkDir} to any of the following branches: {', '.join(branch)}")
        if not targetDir:
            targetDir = repoWorkDir

    assert not isabs(relTargetSuiteDir)
    targetSuiteDir = join(targetDir, relTargetSuiteDir)
    assert targetSuiteDir.startswith(targetDir)
    mxpy = None if suite != mx._mx_suite else join(mirror, 'mx.py')
    for command in mxCommands:
        mx.logv('[running "mx ' + ' '.join(command) + '" in ' + targetSuiteDir + ']')
        mx.run_mx(command, targetSuiteDir, mxpy=mxpy)


@mx.command('mx', 'checkout-downstream', usage_msg='[upstream suite] [downstream suite]\n\nWorks only with Git repositories.\n\nExample:\nmx checkout-downstream compiler graal-enterprise')
@mx.no_suite_loading
def checkout_downstream(args):
    """checkout a revision of the downstream suite that imports the commit checked-out in the upstream suite, or the closest parent commit"""
    parser = ArgumentParser(prog='mx checkout-downstream', description='Checkout a revision of the downstream suite that imports the currently checked-out version of the upstream suite')
    parser.add_argument('upstream', action='store', help='the name of the upstream suite (e.g., compiler)')
    parser.add_argument('downstream', action='store', help='the name of the downstream suite (e.g., graal-enterprise)')
    parser.add_argument('--no-fetch', action='store_true', help='do not fetch remote content for the upstream and downstream repositories')
    args = parser.parse_args(args)

    def get_suite(name):
        suite = mx.suite(name, fatalIfMissing=False)
        if suite is None:
            mx.abort(f"Cannot load the '{name}' suite. Did you forget a dynamic import or pass a repository name rather than a suite name (e.g., 'graal' rather than 'compiler')?")
        return suite

    upstream_suite = get_suite(args.upstream)
    downstream_suite = get_suite(args.downstream)

    if upstream_suite.vc_dir == downstream_suite.vc_dir:
        mx.abort(f"Suites '{upstream_suite.name}' and '{downstream_suite.name}' are part of the same repository, cloned in '{upstream_suite.vc_dir}'")
    if len(downstream_suite.suite_imports) == 0:
        mx.abort(f"Downstream suite '{downstream_suite.name}' does not have dependencies")
    if upstream_suite.name not in (suite_import.name for suite_import in downstream_suite.suite_imports):
        valid_deps = '\n - '.join([s.name for s in downstream_suite.suite_imports])
        mx.abort(f"'{upstream_suite.name}' is not a dependency of '{downstream_suite.name}'. Valid dependencies are:\n - {valid_deps}")

    git = mx.GitConfig()
    for suite in upstream_suite, downstream_suite:
        if not git.is_this_vc(suite.vc_dir):
            mx.abort(f"Suite '{suite.name}' is not part of a Git repo.")

    if not args.no_fetch:
        mx.log(f"Fetching remote content from '{git.default_pull(downstream_suite.vc_dir)}'")
        git.pull(downstream_suite.vc_dir, rev=None, update=False, abortOnError=True)

    # Print the revision (`--pretty=%H`) of the first (`--max-count=1`) merge commit (`--merges`) in the upstream repository that contains `PullRequest: ` in the commit message (`--grep=...`)
    upstream_commit_cmd = ['log', '--pretty=%H', '--grep=PullRequest: ', '--merges', '--max-count=1']
    upstream_commit = _run_git_cmd(upstream_suite.vc_dir, upstream_commit_cmd, regex=r'[a-f0-9]{40}$')

    # We now need to find a revision in `downstream_suite` that imports `upstream_commit` of `upstream_suite`.
    # For doing this, we grep the log of a set of branches in `downstream_suite`, checking out the revision of the first branch that matches.
    # As a consequence, the order in which we check branches in `downstream_suite` is fundamental:
    # 1. we check if the `${DOWNSTREAM_BRANCH}` env var is set. If so, we look for branches named `${DOWNSTREAM_BRANCH}` and `${DOWNSTREAM_BRANCH}_gate(_[0-9]+)?`
    # 2. we (optionally) fetch `upstream_suite` and ask git which branches of `upstream_suite` contain `upstream_commit`

    ci_downstream_branch_candidates = []
    ci_downstream_branch = mx.get_env('DOWNSTREAM_BRANCH', None)
    if ci_downstream_branch is not None:
        mx.log(f"The '$DOWNSTREAM_BRANCH' env var is set. Adding '{ci_downstream_branch}' to the list of downstream branch candidates")
        ci_downstream_branch_candidates.append(ci_downstream_branch)
        ci_downstream_branch_candidates += re.findall(ci_downstream_branch + '_gate(?:_[0-9]+)?', _run_git_cmd(downstream_suite.vc_dir, ['branch', '-r']))
        mx.log(f"Complete list of downstream branch candidates: {ci_downstream_branch_candidates}")

    if not _checkout_upstream_revision(upstream_commit, ci_downstream_branch_candidates, upstream_suite, downstream_suite):
        if not args.no_fetch:
            mx.log(f"Fetching remote content from '{git.default_pull(upstream_suite.vc_dir)}'")
            git.pull(upstream_suite.vc_dir, rev=None, update=False, abortOnError=True)

        # Print the list of branches that contain the upstream commit
        upstream_branches_out = _run_git_cmd(upstream_suite.vc_dir, ['branch', '-a', '--contains', upstream_commit])  # old git versions do not support `--format`
        downstream_branch_candidates = []
        for ub in upstream_branches_out.split('\n'):
            ub = re.sub(r'^\*', '', ub).lstrip()
            ub = re.sub('^remotes/origin/', '', ub)
            if not re.match(r'\(HEAD detached at [a-z0-9]+\)$', ub):
                downstream_branch_candidates.append(ub)

        candidates = '\n- '.join(downstream_branch_candidates)
        mx.log(f"The most recent merge performed by the CI on the active branch of the upstream repository is at revision '{upstream_commit}', which is part of the following branches:\n- {candidates}")
        if not _checkout_upstream_revision(upstream_commit, downstream_branch_candidates, upstream_suite, downstream_suite):
            mx.abort(f"Cannot find a revision of '{downstream_suite.vc_dir}' that imports revision '{upstream_commit}' of '{upstream_suite.name}")


def _run_git_cmd(vc_dir, cmd, regex=None, abortOnError=True):
    """
    :type vc_dir: str
    :type cmd: list[str]
    :type regex: str | None
    :type abortOnError: bool
    :rtype: str
    """
    git = mx.GitConfig()
    output = (git.git_command(vc_dir, cmd, abortOnError=abortOnError) or '').strip()
    if regex is not None and re.match(regex, output, re.MULTILINE) is None:
        if abortOnError:
            mx.abort(f"Unexpected output running command '{' '.join(map(shlex.quote, ['git', '-C', vc_dir, '--no-pager'] + cmd))}'. Expected a match for '{regex}', got:\n{output}")
        return None
    return output


def _checkout_upstream_revision(upstream_commit, candidate_downstream_branches, upstream_suite, downstream_suite):
    """
    :type upstream_commit: str
    :type candidate_downstream_branches: str
    :type upstream_suite: str
    :type downstream_suite: str
    :rtype: bool
    """
    for candidate_downstream_branch in candidate_downstream_branches:
        mx.log(f"Analyzing branch '{candidate_downstream_branch}':")
        rev_parse_output = _run_git_cmd(downstream_suite.vc_dir, ['rev-parse', '--verify', f'origin/{candidate_downstream_branch}'], regex=r'[a-f0-9]{40}$', abortOnError=False)
        if rev_parse_output is None:
            mx.log(f" - the downstream repository does not contain a branch named '{candidate_downstream_branch}'")
            continue
        mx.log(f" - the downstream repository contains a branch named '{candidate_downstream_branch}'")
        downstream_branch = candidate_downstream_branch

        mx.log(f" - searching the 'origin/{downstream_branch}' branch of the downstream repo in '{downstream_suite.vc_dir}' for a commit that imports revision '{upstream_commit}' of '{upstream_suite.name}'")
        # Print the oldest (`--reverse`) revision (`--pretty=%H`) of a commit in the matching branch of the repository of the downstream suite that contains `PullRequest: ` in the commit message (`--grep=...` and `-m`) and mentions the upstream commit (`-S`)
        downstream_commit_cmd = ['log', f'origin/{downstream_branch}', '--pretty=%H', '--grep=PullRequest: ', '--reverse', '-m', '-S', upstream_commit, '--', downstream_suite.suite_py()]
        downstream_commit = _run_git_cmd(downstream_suite.vc_dir, downstream_commit_cmd, regex=r'[a-f0-9]{40}(\n[a-f0-9]{40})?$', abortOnError=False)
        if downstream_commit is None:
            mx.log(f" - cannot find a revision in branch 'origin/{downstream_branch}' of '{downstream_suite.vc_dir}' that imports revision '{upstream_commit}' of '{upstream_suite.name}'")
            continue
        downstream_commit = downstream_commit.split('\n')[0]
        mx.log(f"Checking out revision '{downstream_commit}' of downstream suite '{downstream_suite.name}', which imports revision '{upstream_commit}' of '{upstream_suite.name}'")
        mx.GitConfig().update(downstream_suite.vc_dir, downstream_commit, mayPull=False, clean=False, abortOnError=True)
        return True
    return False
