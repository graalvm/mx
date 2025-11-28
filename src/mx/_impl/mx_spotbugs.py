#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2025, Oracle and/or its affiliates. All rights reserved.
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

__all__ = [
    "defaultSpotbugsArgs",
    "spotbugs",
]

from argparse import ArgumentParser

from . import mx
import os
import tempfile
import zipfile
import shutil
from os.path import join, exists

def _max_jdk_version_supported(spotbugs_version):
    """
    Gets the max JDK version supported by `spotbugs_version`.

    Information is derived from https://github.com/spotbugs/spotbugs/blob/master/CHANGELOG.md
    """
    v = mx.VersionSpec(spotbugs_version)
    if v >= mx.VersionSpec('4.9.8'):
        return 25
    if v >= mx.VersionSpec('4.7.3_JDK21_BACKPORT'):
        return 21
    if v >= mx.VersionSpec('4.7.3'):
        return 20
    if v >= mx.VersionSpec('4.7.0'):
        return 19
    if v >= mx.VersionSpec('4.3.0'):
        return 18
    if v >= mx.VersionSpec('4.2.2'):
        return 17
    if v >= mx.VersionSpec('4.1.4'):
        return 16
    if v >= mx.VersionSpec('3.1.9'):
        return 11
    return 8

def defaultSpotbugsArgs():
    """
    Gets the default args passed directly through to spotbugs.
    """
    args = ['-textui', '-low', '-maxRank', '15']
    if mx.is_interactive():
        args.append('-progress')
    return args

def _get_spotbugs_attribute(p, suffix, default=None):
    return getattr(p, 'spotbugs' + suffix, default)

def _should_test_project(p):
    if not p.isJavaProject():
        return False
    spotbugs_attribute_value = _get_spotbugs_attribute(p, '', None)
    if spotbugs_attribute_value is not None:
        if isinstance(spotbugs_attribute_value, bool):
            return spotbugs_attribute_value
        return spotbugs_attribute_value.lower() == 'true'
    if p.is_test_project():
        return False
    if p.javaCompliance >= '9':
        compat = p.suite.getMxCompatibility()
        if compat.spotbugs_limited_to_8():
            return False
    # Return the suite-level default
    return p.suite.spotbugs


def _warn_or_abort(msg, strict_mode):
    reporter = mx.abort if strict_mode else mx.warn
    reporter(msg)


def spotbugs(args, spotbugsArgs=None, suite=None, projects=None, jarFileName='spotbugs.jar'):
    """

    :param spotbugsArgs: args passed directly through to spotbugs
    """
    parser = ArgumentParser(prog='mx spotbugs')
    parser.add_argument('--strict-mode', action='store_true', help='abort if SpotBugs cannot be executed for some reason (e.g., unsupported JDK version)')
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    parsed_args, remaining_args = parser.parse_known_args(args)

    projectsToTest = [p for p in mx.projects(limit_to_primary=parsed_args.primary) if _should_test_project(p)]
    projectsByVersion = {}
    for p in projectsToTest:
        compat = p.suite.getMxCompatibility()
        spotbugsVersion = compat.spotbugs_version()
        projectsByVersion.setdefault(spotbugsVersion, []).append(p)
        max_jdk_version_supported = _max_jdk_version_supported(spotbugsVersion)
        if _max_jdk_version_supported(spotbugsVersion) < p.javaCompliance.value:
            if getattr(p, "spotbugsStrict", True) is False:
                mx.warn(f'Spotbugs {spotbugsVersion} only runs on JDK {max_jdk_version_supported} or lower, not {p.javaCompliance}. Skipping {p}')

    resultcode = 0
    for spotbugsVersion, versionProjects in projectsByVersion.items():
        mx.log(f'Running spotbugs version {spotbugsVersion}')
        mx.logv('Projects to check:\n' + ('\n  '.join([x.name for x in versionProjects])))
        resultcode = max(resultcode, _spotbugs(parsed_args, remaining_args, spotbugsArgs, suite, versionProjects, spotbugsVersion))
    return resultcode

def _spotbugs(parsed_args, args, spotbugsArgs, suite, projectsToTest, spotbugsVersion):
    """run SpotBugs against non-test Java projects

    :param spotbugsArgs: args passed directly through to spotbugs
    """

    spotbugsHome = mx.get_env('SPOTBUGS_HOME', None)
    jarFileName = 'spotbugs.jar'
    if suite is None:
        suite = mx.primary_suite()
    if spotbugsHome:
        spotbugsJar = join(spotbugsHome, 'lib', jarFileName)
    else:
        spotbugsLib = join(mx._mx_suite.get_output_root(), 'spotbugs-' + spotbugsVersion)
        if not exists(spotbugsLib):
            tmp = tempfile.mkdtemp(prefix='spotbugs-download-tmp', dir=mx._mx_suite.dir)
            try:
                spotbugsDist = mx.library('SPOTBUGS_' + spotbugsVersion).get_path(resolve=True)
                with zipfile.ZipFile(spotbugsDist) as zf:
                    candidates = [e for e in zf.namelist() if e.endswith('/lib/' + jarFileName)]
                    assert len(candidates) == 1, candidates
                    libDirInZip = os.path.dirname(candidates[0])
                    zf.extractall(tmp)
                shutil.copytree(join(tmp, libDirInZip), spotbugsLib)
            finally:
                shutil.rmtree(tmp)
        spotbugsJar = join(spotbugsLib, jarFileName)
    assert exists(spotbugsJar)
    if not projectsToTest:
        return 0

    ignoredClasses = set()
    for p in projectsToTest:
        ignore = _get_spotbugs_attribute(p, 'IgnoresGenerated', False)
        if not isinstance(ignore, bool):
            mx.abort('Value of attribute "spotbugsIgnoresGenerated" must be True or False', context=p)
        if ignore is True:
            sourceDir = p.source_gen_dir()
            for root, _, files in os.walk(sourceDir):
                for name in files:
                    if name.endswith('.java') and '-info' not in name:
                        pkg = root[len(sourceDir) + 1:].replace(os.sep, '.')
                        cls = pkg + '.' + name[:-len('.java')]
                        ignoredClasses.add(cls)

    with tempfile.NamedTemporaryFile(suffix='.xml', prefix='spotbugs_exclude_filter.', mode='w', delete=False) as fp:
        spotbugsExcludeFilterFile = fp.name
        xmlDoc = mx.XMLDoc()

        xmlDoc.open('FindBugsFilter')
        # There is at least one bug (https://github.com/spotbugs/spotbugs/issues/1791)
        # in SpotBugs that causes false positives for the redundant null tests.
        # This rule is disabled until such time there is a SpotBugs release
        # that does not generate these false positives.
        xmlDoc.open('Match')
        xmlDoc.element('Bug', attributes={'pattern' : 'RCN_REDUNDANT_NULLCHECK_WOULD_HAVE_BEEN_A_NPE'})
        xmlDoc.close('Match')

        for cls in ignoredClasses:
            xmlDoc.open('Match')
            xmlDoc.element('Class', attributes={'name' : '~' + cls + '.*'})
            xmlDoc.close('Match')
        xmlDoc.close('FindBugsFilter')
        xml = xmlDoc.xml(indent='  ', newl='\n')
        print(xml, file=fp)

    outputDirs = [mx._cygpathU2W(p.output_dir()) for p in projectsToTest]
    javaCompliance = max([p.javaCompliance for p in projectsToTest])
    max_jdk_version = _max_jdk_version_supported(spotbugsVersion)
    if max_jdk_version < javaCompliance.value:
        _warn_or_abort(
            f'Spotbugs {spotbugsVersion} only runs on JDK {max_jdk_version} or lower, not {javaCompliance}. Skipping {projectsToTest}',
            parsed_args.strict_mode)
        return 0
    _range = f'{javaCompliance.value}..{max_jdk_version}' if javaCompliance.value < max_jdk_version else str(max_jdk_version)

    # If SPOTBUGS_HOME is set, then assume that it can be run with JAVA_HOME
    jdk = mx.get_jdk() if spotbugsHome else mx.get_tools_jdk(_range, purpose='SpotBugs')

    spotbugsResults = join(suite.dir, 'spotbugs.results')

    if spotbugsArgs is None:
        spotbugsArgs = defaultSpotbugsArgs()
    cmd = ['-jar', mx._cygpathU2W(spotbugsJar)] + spotbugsArgs
    cmd = cmd + ['-exclude', spotbugsExcludeFilterFile]
    cmd = cmd + ['-auxclasspath', mx._separatedCygpathU2W(mx.classpath([p.name for p in projectsToTest], jdk=jdk)), '-output', mx._cygpathU2W(spotbugsResults), '-exitcode'] + args + outputDirs
    try:
        exitcode = mx.run_java(cmd, nonZeroIsFatal=False, jdk=jdk)
    finally:
        os.unlink(spotbugsExcludeFilterFile)
    if exitcode != 0:
        with open(spotbugsResults) as fp:
            mx.log(fp.read())
    os.unlink(spotbugsResults)
    return exitcode
