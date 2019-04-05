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

from __future__ import print_function

import mx
import os
import tempfile
import zipfile
import shutil
from os.path import join, exists

def defaultFindbugsArgs():
    args = ['-textui', '-low', '-maxRank', '15']
    if mx.is_interactive():
        args.append('-progress')
    return args

def _get_spotbugs_attribute(p, suffix, default=None):
    spotbugs_attribute_value = None
    attributes = [s + suffix for s in ('spotbugs', 'findbugs')]
    found = False
    for spotbugs_attribute_name in attributes:
        if hasattr(p, spotbugs_attribute_name):
            if spotbugs_attribute_value is not None:
                mx.abort('Spotbugs attribute "{}" is redundant. Please use attribute "{}" instead'.format(spotbugs_attribute_name, attributes[0]), context=p)
            spotbugs_attribute_value = getattr(p, spotbugs_attribute_name)
            found = True
    return spotbugs_attribute_value if found else default

def _should_test_project(p):
    spotbugs_attribute_value = _get_spotbugs_attribute(p, '')
    if spotbugs_attribute_value is not None:
        if p.isJavaProject():
            return spotbugs_attribute_value.lower() == 'true' or spotbugs_attribute_value is True
        else:
            return spotbugs_attribute_value.lower() == 'always'
    if not p.isJavaProject():
        return False
    if p.is_test_project():
        return False
    if p.javaCompliance >= '9':
        # We no longer use p.suite.getMxCompatibility().filterFindbugsProjectsByJavaCompliance()
        # as we don't want projects with Java compliance greater than 8 to ever prevent FindBugs
        # being run on projects with compliance less than or equal to 8.
        return False
    return True

def spotbugs(args, fbArgs=None, suite=None, projects=None, jarFileName='spotbugs.jar'):
    projectsToTest = [p for p in mx.projects() if _should_test_project(p)]
    projectsByVersion = {}
    for p in projectsToTest:
        compat = p.suite.getMxCompatibility()
        spotbugsVersion = compat.spotbugs_version()
        if spotbugsVersion not in projectsByVersion:
            projectsByVersion[spotbugsVersion] = []
        projectsByVersion[spotbugsVersion].append(p)
    resultcode = 0
    for spotbugsVersion, versionProjects in projectsByVersion.items():
        mx.logv('Running spotbugs version {} on projects {}'.format(spotbugsVersion, versionProjects))
        resultcode = max(resultcode, _spotbugs(args, fbArgs, suite, versionProjects, spotbugsVersion))
    return resultcode

def _spotbugs(args, fbArgs, suite, projectsToTest, spotbugsVersion):
    """run FindBugs against non-test Java projects"""
    findBugsHome = mx.get_env('SPOTBUGS_HOME', mx.get_env('FINDBUGS_HOME', None))
    if spotbugsVersion == '3.0.0':
        jarFileName = 'findbugs.jar'
    else:
        jarFileName = 'spotbugs.jar'
    if suite is None:
        suite = mx.primary_suite()
    if findBugsHome:
        spotbugsJar = join(findBugsHome, 'lib', jarFileName)
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
        if spotbugsVersion == '3.0.0':
            # Javac from JDK11 might have been used to compile the classes so
            # disable the check for redundant null tests since FindBugs does
            # not (yet) detect and suppress warnings about patterns generated by
            # this version of javac. This will be removed once
            # https://github.com/spotbugs/spotbugs/issues/600 is resolved.
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
    jdk = mx.get_jdk(javaCompliance)
    if jdk.javaCompliance >= '9':
        mx.log('FindBugs does not yet support JDK9 - skipping')
        return 0

    spotbugsResults = join(suite.dir, 'spotbugs.results')

    if fbArgs is None:
        fbArgs = defaultFindbugsArgs()
    cmd = ['-jar', mx._cygpathU2W(spotbugsJar)] + fbArgs
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
