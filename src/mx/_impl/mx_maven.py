#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2026, Oracle and/or its affiliates. All rights reserved.
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

from __future__ import annotations

__all__ = [
    "MavenArtifactVersions",
    "MavenSnapshotBuilds",
    "MavenSnapshotArtifact",
    "MavenRepo",
    "maven_local_repository",
    "maven_download_urls",
    "deploy_binary",
    "maven_deploy",
    "deploy_artifacts",
    "maven_url",
    "binary_url",
    "MavenConfig",
    "maven_install",
]

from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime
import fnmatch
from io import StringIO
import json
import os
from os.path import exists, join
import shlex
import shutil
import tempfile
import urllib
import uuid
from xml.dom.minidom import parseString as minidomParseString
import zipfile

try:
    # Use more secure defusedxml library, if available
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse

from . import mx
from .mx_javamodules import as_java_module


def _map_to_maven_dist_name(name):
    return name.lower().replace('_', '-')


class MavenArtifactVersions:
    def __init__(self, latestVersion, releaseVersion, versions):
        self.latestVersion = latestVersion
        self.releaseVersion = releaseVersion
        self.versions = versions


class MavenSnapshotBuilds:
    def __init__(self, currentTime, currentBuildNumber, snapshots):
        self.currentTime = currentTime
        self.currentBuildNumber = currentBuildNumber
        self.snapshots = snapshots

    def getCurrentSnapshotBuild(self):
        return self.snapshots[(self.currentTime, self.currentBuildNumber)]


class MavenSnapshotArtifact:
    def __init__(self, groupId, artifactId, version, snapshotBuildVersion, repo):
        self.groupId = groupId
        self.artifactId = artifactId
        self.version = version
        self.snapshotBuildVersion = snapshotBuildVersion
        self.subArtifacts = []
        self.repo = repo

    class SubArtifact:
        def __init__(self, extension, classifier):
            self.extension = extension
            self.classifier = classifier

        def __repr__(self):
            return str(self)

        def __str__(self):
            return f"{self.classifier}.{self.extension}" if self.classifier else self.extension

    def addSubArtifact(self, extension, classifier):
        self.subArtifacts.append(self.SubArtifact(extension, classifier))

    class NonUniqueSubArtifactException(Exception):
        pass

    def _getUniqueSubArtifact(self, criterion):
        filtered = [sub for sub in self.subArtifacts if criterion(sub.extension, sub.classifier)]
        if len(filtered) == 0:
            return None
        if len(filtered) > 1:
            raise self.NonUniqueSubArtifactException()
        sub = filtered[0]
        group = self.groupId.replace('.', '/')
        classifier = f'-{sub.classifier}' if sub.classifier else ''
        url = f"{self.repo.repourl}/{group}/{self.artifactId}/{self.version}/{self.artifactId}-{self.snapshotBuildVersion}{classifier}.{sub.extension}"
        return url, url + '.sha1'

    def getSubArtifact(self, extension, classifier=None):
        return self._getUniqueSubArtifact(lambda e, c: e == extension and c == classifier)

    def getSubArtifactByClassifier(self, classifier):
        return self._getUniqueSubArtifact(lambda e, c: c == classifier)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"{self.groupId}:{self.artifactId}:{self.snapshotBuildVersion}-SNAPSHOT"


class MavenRepo:
    def __init__(self, repourl):
        self.repourl = repourl
        self.artifactDescs = {}

    def getArtifactVersions(self, groupId, artifactId):
        metadataUrl = f"{self.repourl}/{groupId.replace('.', '/')}/{artifactId}/maven-metadata.xml"
        mx.logv(f'Retrieving and parsing {metadataUrl}')
        try:
            metadataFile = mx._urlopen(metadataUrl, timeout=10)
        except urllib.error.HTTPError as e:
            mx._suggest_http_proxy_error(e)
            mx.abort(f'Error while retrieving metadata for {groupId}:{artifactId}: {str(e)}')
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId

            versioning = root.find('versioning')
            latest = versioning.find('latest')
            release = versioning.find('release')
            versions = versioning.find('versions')
            versionStrings = [v.text for v in versions.iter('version')]
            releaseVersionString = release.text if release is not None and len(release) != 0 else None
            if latest is not None and len(latest) != 0:
                latestVersionString = latest.text
            else:
                mx.logv('Element \'latest\' not specified in metadata. Fallback: Find latest via \'versions\'.')
                latestVersionString = None
                for version_str in reversed(versionStrings):
                    snapshot_metadataUrl = self.getSnapshotUrl(groupId, artifactId, version_str)
                    try:
                        snapshot_metadataFile = mx._urlopen(snapshot_metadataUrl, timeout=10)
                    except urllib.error.HTTPError:
                        mx.logv(f'Version {metadataUrl} not accessible. Try previous snapshot.')
                        snapshot_metadataFile = None

                    if snapshot_metadataFile:
                        mx.logv(f'Using version {version_str} as latestVersionString.')
                        latestVersionString = version_str
                        snapshot_metadataFile.close()
                        break

            return MavenArtifactVersions(latestVersionString, releaseVersionString, versionStrings)
        except urllib.error.URLError as e:
            mx.abort(f'Error while retrieving versions for {groupId}:{artifactId}: {str(e)}')
        finally:
            if metadataFile:
                metadataFile.close()

    def getSnapshotUrl(self, groupId, artifactId, version):
        return f"{self.repourl}/{groupId.replace('.', '/')}/{artifactId}/{version}/maven-metadata.xml"

    def getSnapshot(self, groupId, artifactId, version):
        assert version.endswith('-SNAPSHOT')
        metadataUrl = self.getSnapshotUrl(groupId, artifactId, version)
        mx.logv(f'Retrieving and parsing {metadataUrl}')
        try:
            metadataFile = mx._urlopen(metadataUrl, timeout=10)
        except urllib.error.URLError as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                return None
            mx._suggest_http_proxy_error(e)
            mx.abort(f'Error while retrieving snapshot for {groupId}:{artifactId}:{version}: {str(e)}')
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId
            assert root.find('version').text == version

            versioning = root.find('versioning')
            snapshot = versioning.find('snapshot')
            snapshotVersions = versioning.find('snapshotVersions')
            currentSnapshotTime = snapshot.find('timestamp').text
            currentSnapshotBuildElement = snapshot.find('buildNumber')
            currentSnapshotBuildNumber = int(currentSnapshotBuildElement.text) if currentSnapshotBuildElement is not None else 0

            versionPrefix = version[:-len('-SNAPSHOT')] + '-'
            prefixLen = len(versionPrefix)
            snapshots = {}
            for snapshotVersion in snapshotVersions.iter('snapshotVersion'):
                fullVersion = snapshotVersion.find('value').text
                separatorIndex = fullVersion.index('-', prefixLen)
                timeStamp = fullVersion[prefixLen:separatorIndex]
                buildNumber = int(fullVersion[separatorIndex+1:])
                extension = snapshotVersion.find('extension').text
                classifier = snapshotVersion.find('classifier')
                classifierString = None
                if classifier is not None and len(classifier.text) > 0:
                    classifierString = classifier.text
                artifact = snapshots.setdefault((timeStamp, buildNumber), MavenSnapshotArtifact(groupId, artifactId, version, fullVersion, self))

                artifact.addSubArtifact(extension, classifierString)
            return MavenSnapshotBuilds(currentSnapshotTime, currentSnapshotBuildNumber, snapshots)
        finally:
            if metadataFile:
                metadataFile.close()


_maven_local_repository = None


def maven_local_repository():  # pylint: disable=invalid-name
    global _maven_local_repository

    if not _maven_local_repository:
        class _MavenLocalRepository(mx.Repository):
            """This singleton class represents mavens local repository (usually under ~/.m2/repository)"""

            def __init__(self):
                try:
                    res = {'lines': '', 'xml': False, 'total_output': ''}

                    def xml_settings_grabber(line):
                        res['total_output'] += line
                        if not res['xml'] and not res['lines'] and line.startswith('<settings '):
                            res['xml'] = True
                        if res['xml']:
                            res['lines'] += line
                            if line.startswith('</settings>'):
                                res['xml'] = False

                    mx.run_maven(['help:effective-settings'], out=xml_settings_grabber)
                    dom = minidomParseString(res['lines'])
                    local_repo = dom.getElementsByTagName('localRepository')[0].firstChild.data
                    url = 'file://' + local_repo
                except BaseException as e:
                    ls = os.linesep
                    mx.abort(f"Unable to determine maven local repository URL{ls}Caused by: {repr(e)}{ls}Output:{ls}{res['total_output']}")
                super().__init__(mx.suite('mx'), 'maven local repository', url, url, [])

            def resolveLicenses(self):
                return True

        _maven_local_repository = _MavenLocalRepository()

    return _maven_local_repository


def maven_download_urls(groupId, artifactId, version, classifier=None, baseURL=None):
    if baseURL is None:
        baseURLs = mx._mavenRepoBaseURLs
    else:
        baseURLs = [baseURL]
    classifier = f'-{classifier}' if classifier else ''
    return [f"{base}{groupId.replace('.', '/')}/{artifactId}/{version}/{artifactId}-{version}{classifier}.jar" for base in baseURLs]


### ~~~~~~~~~~~~~ Maven, _private


def _mavenGroupId(suite):
    if isinstance(suite, mx.Suite):
        group_id = suite._get_early_suite_dict_property('groupId')
        if group_id:
            return group_id
        name = suite.name
    else:
        assert isinstance(suite, str)
        name = suite
    return 'com.oracle.' + _map_to_maven_dist_name(name)


def _maven_direct_pom_dependencies(dist):
    directDistDeps = [d for d in dist.deps if d.isDistribution() and not d.isLayoutDirDistribution()]
    directLibDeps = dist.excludedLibs
    return directDistDeps, directLibDeps


def _maven_emitted_direct_pom_dependencies(dist):
    directDistDeps, directLibDeps = _maven_direct_pom_dependencies(dist)
    emittedDistDeps = [dep for dep in directDistDeps if not dep.suite.internal]
    emittedLibDeps = []
    for lib in directLibDeps:
        if (lib.isJdkLibrary() or lib.isJreLibrary()) and lib.is_provided_by(mx.get_jdk()) and lib.is_provided_by(mx.get_jdk(dist.maxJavaCompliance())):
            continue
        emittedLibDeps.append(lib)
    return emittedDistDeps, emittedLibDeps


def _deployment_module_requires_for_maven(dist):
    if not dist.isJARDistribution():
        return None, None

    from . import mx_javamodules

    module_name = mx_javamodules.get_module_name(dist)
    if not module_name:
        return None, None

    deployment_module_info = dist.maven.get('moduleInfo') if isinstance(dist.maven, dict) else None
    jdk = mx.get_jdk(tag='default')
    if jdk.javaCompliance > '1.8':
        jmd = as_java_module(dist, jdk, fatalIfNotCreated=False)
        if jmd:
            if deployment_module_info:
                if not jmd.alternatives:
                    return module_name, None
                alt_jmd = jmd.alternatives.get(deployment_module_info)
                if not alt_jmd:
                    return module_name, None
                jmd = alt_jmd
            return jmd.name, jmd.requires

    module_info_attr = 'moduleInfo'
    if deployment_module_info:
        module_info_attr += ':' + deployment_module_info
    module_info = getattr(dist, module_info_attr, None)
    if not module_info:
        return module_name, None

    requires = {}
    for entry in module_info.get('requires', []):
        parts = entry.split()
        if parts:
            requires[parts[-1]] = set(parts[:-1])
    return module_name, requires


def _lint_maven_optional_dependencies(dist, overrides):
    module_name, requires = _deployment_module_requires_for_maven(dist)
    if not module_name or not requires:
        return

    from . import mx_javamodules

    for dep, meta in overrides.items():
        if not meta.get('optional', False) or not dep.isDistribution():
            continue
        dep_module_name = mx_javamodules.get_module_name(dep)
        if not dep_module_name:
            continue
        modifiers = requires.get(dep_module_name)
        if modifiers is not None and 'static' not in modifiers:
            dist.warn(f'Maven dependency {dep.qualifiedName()} is marked optional, but deployed module {module_name} requires {dep_module_name} without "static". Downstream JPMS consumers may need to add this dependency explicitly.')


def _validated_maven_dependency_metadata(dist):
    metadata = getattr(dist, '.validated_maven_dependency_metadata', None)
    if metadata is not None:
        return metadata

    directDistDeps, directLibDeps = _maven_emitted_direct_pom_dependencies(dist)
    directPomDeps = directDistDeps + directLibDeps

    metadata = {}
    for dep in getattr(dist, 'optionalDependencies', []):
        if dep in directPomDeps:
            metadata[dep] = {'optional': True}

    _lint_maven_optional_dependencies(dist, metadata)
    setattr(dist, '.validated_maven_dependency_metadata', metadata)
    return metadata


def _genPom(dist, versionGetter, validateMetadata='none'):
    """
    :type dist: Distribution
    """
    groupId = dist.maven_group_id()
    artifactId = dist.maven_artifact_id()
    version = versionGetter(dist.suite)

    if hasattr(dist, "generate_deployment_pom"):
        if validateMetadata == 'full':
            cb = mx.abort
        elif validateMetadata != 'none':
            cb = None
        else:
            cb = mx.warn
        return dist.generate_deployment_pom(version, validation_callback=cb)

    pom = mx.XMLDoc()
    pom.open('project', attributes={
        'xmlns': "http://maven.apache.org/POM/4.0.0",
        'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'xsi:schemaLocation': "http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"
        })
    pom.element('modelVersion', data="4.0.0")
    pom.element('groupId', data=groupId)
    pom.element('artifactId', data=artifactId)
    pom.element('version', data=version)
    if dist.remoteExtension() != 'jar':
        pom.element('packaging', data=dist.remoteExtension())
    if dist.suite.url:
        pom.element('url', data=dist.suite.url)
    elif validateMetadata != 'none':
        if 'suite-url' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            mx.abort(f"Suite {dist.suite.name} is missing the 'url' attribute")
        mx.warn(f"Suite {dist.suite.name}'s  version is too old to contain the 'url' attribute")
    acronyms = ['API', 'DSL', 'SL', 'TCK']
    name = ' '.join((t if t in acronyms else t.lower().capitalize() for t in dist.name.split('_')))
    pom.element('name', data=name)
    if hasattr(dist, 'description'):
        pom.element('description', data=dist.description)
    elif validateMetadata != 'none':
        if 'dist-description' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            dist.abort("Distribution is missing the 'description' attribute")
        dist.warn("Distribution's suite version is too old to have the 'description' attribute")
    if dist.suite.developer:
        pom.open('developers')
        pom.open('developer')

        def _addDevAttr(name, default=None):
            if name in dist.suite.developer:
                value = dist.suite.developer[name]
            else:
                value = default
            if value:
                pom.element(name, data=value)
            elif validateMetadata != 'none':
                mx.abort(f"Suite {dist.suite.name}'s developer metadata is missing the '{name}' attribute")

        _addDevAttr('name')
        _addDevAttr('email')
        _addDevAttr('organization')
        _addDevAttr('organizationUrl', dist.suite.url)
        pom.close('developer')
        pom.close('developers')
    elif validateMetadata != 'none':
        if 'suite-developer' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            mx.abort(f"Suite {dist.suite.name} is missing the 'developer' attribute")
        mx.warn(f"Suite {dist.suite.name}'s version is too old to contain the 'developer' attribute")
    if dist.theLicense:
        pom.open('licenses')
        for distLicense in dist.theLicense:
            pom.open('license')
            pom.element('name', data=distLicense.fullname)
            pom.element('url', data=distLicense.url)
            pom.close('license')
        pom.close('licenses')
    elif validateMetadata != 'none':
        if dist.suite.getMxCompatibility().supportsLicenses() or validateMetadata == 'full':
            dist.abort("Distribution is missing 'license' attribute")
        dist.warn("Distribution's suite version is too old to have the 'license' attribute")
    directDistDeps, directLibDeps = _maven_direct_pom_dependencies(dist)
    mavenDependencyMetadata = _validated_maven_dependency_metadata(dist)
    if directDistDeps or directLibDeps:
        pom.open('dependencies')
        for dep in directDistDeps:
            if dep.suite.internal:
                mx.warn(f"_genPom({dist}): ignoring internal dependency {dep}")
                continue
            if validateMetadata != 'none' and not getattr(dep, 'maven', False):
                if validateMetadata == 'full':
                    dist.abort(f"Distribution depends on non-maven distribution {dep}")
                dist.warn(f"Distribution depends on non-maven distribution {dep}")
            for platform in dep.platforms:
                pom.open('dependency')
                pom.element('groupId', data=dep.maven_group_id())
                pom.element('artifactId', data=dep.maven_artifact_id(platform=platform))
                dep_version = versionGetter(dep.suite)
                if validateMetadata != 'none' and 'SNAPSHOT' in dep_version and 'SNAPSHOT' not in version:
                    if validateMetadata == 'full':
                        dist.abort(f"non-snapshot distribution depends on snapshot distribution {dep}")
                    dist.warn(f"non-snapshot distribution depends on snapshot distribution {dep}")
                pom.element('version', data=dep_version)
                if dep.remoteExtension() != 'jar':
                    pom.element('type', data=dep.remoteExtension())
                if dist.isPOMDistribution() and dist.is_runtime_dependency(dep):
                    pom.element('scope', data='runtime')
                if mavenDependencyMetadata.get(dep, {}).get('optional', False):
                    pom.element('optional', data='true')
                pom.close('dependency')
        for l in directLibDeps:
            if (l.isJdkLibrary() or l.isJreLibrary()) and l.is_provided_by(mx.get_jdk()) and l.is_provided_by(mx.get_jdk(dist.maxJavaCompliance())):
                continue
            if hasattr(l, 'maven'):
                mavenMetaData = l.maven
                pom.open('dependency')
                pom.element('groupId', data=mavenMetaData['groupId'])
                pom.element('artifactId', data=mavenMetaData['artifactId'])
                pom.element('version', data=mavenMetaData['version'])
                if dist.suite.getMxCompatibility().mavenSupportsClassifier():
                    if 'suffix' in mavenMetaData:
                        l.abort('The use of "suffix" as maven metadata is not supported in this version. Use "classifier" instead.')
                    if 'classifier' in mavenMetaData:
                        pom.element('classifier', data=mavenMetaData['classifier'])
                else:
                    if 'suffix' in mavenMetaData:
                        pom.element('classifier', data=mavenMetaData['suffix'])
                if mavenDependencyMetadata.get(l, {}).get('optional', False):
                    pom.element('optional', data='true')
                pom.close('dependency')
            elif validateMetadata != 'none':
                if 'library-coordinates' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
                    l.abort("Library is missing maven metadata")
                l.warn("Library's suite version is too old to have maven metadata")
        pom.close('dependencies')
    if dist.suite.vc:
        pom.open('scm')
        scm = dist.suite.scm_metadata(abortOnError=validateMetadata != 'none')
        pom.element('connection', data=f'scm:{dist.suite.vc.kind}:{scm.read}')
        if scm.read != scm.write or validateMetadata == 'full':
            pom.element('developerConnection', data=f'scm:{dist.suite.vc.kind}:{scm.write}')
        pom.element('url', data=scm.url)
        pom.close('scm')
    elif validateMetadata == 'full':
        mx.abort(f"Suite {dist.suite.name} is not in a vcs repository, as a result 'scm' attribute cannot be generated for it")
    pom.close('project')
    return pom.xml(indent='  ', newl='\n')


def _tmpPomFile(dist, versionGetter, validateMetadata='none'):
    with tempfile.NamedTemporaryFile('w', suffix='.pom', delete=False) as tmp:
        tmp.write(_genPom(dist, versionGetter, validateMetadata))
        return tmp.name


@dataclass
class _MavenDeploySpec:
    group_id: str
    artifact_id: str
    version: str
    file_path: str
    extension: str
    pom_file: str | None = None
    src_path: str | None = None
    javadoc_path: str | None = None
    extra_files: list[tuple[str, str, str]] | None = None


def _create_maven_deploy_spec(groupId, artifactId, filePath, version,
                              srcPath=None,
                              extension='jar',
                              pomFile=None,
                              javadocPath=None,
                              extraFiles=None):
    return _MavenDeploySpec(group_id=groupId,
                            artifact_id=artifactId,
                            version=version,
                            file_path=filePath,
                            extension=extension,
                            pom_file=pomFile,
                            src_path=srcPath,
                            javadoc_path=javadocPath,
                            extra_files=extraFiles)


def _maven_batch_command(settingsXml):
    cmd = ['--batch-mode']

    if not mx._opts.verbose:
        cmd.append('--quiet')

    if mx._opts.verbose:
        cmd.append('--errors')

    if mx._opts.very_verbose:
        cmd.append('--debug')

    if settingsXml:
        cmd += ['-s', settingsXml]

    return cmd


def _write_batched_maven_deploy_pom(specs, repo):
    plugin_group_id = 'org.apache.maven.plugins'
    plugin_artifact_id = 'maven-install-plugin' if repo == maven_local_repository() else 'maven-deploy-plugin'
    plugin_goal = 'install-file' if repo == maven_local_repository() else 'deploy-file'
    plugin_version = '3.1.1'  # Requires Maven 3.2.5+

    pom = mx.XMLDoc()
    pom.open('project', attributes={
        'xmlns': "http://maven.apache.org/POM/4.0.0",
        'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'xsi:schemaLocation': "http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"
    })
    pom.element('modelVersion', data='4.0.0')
    pom.element('groupId', data='mx.internal')
    pom.element('artifactId', data='mx-batch-maven-deploy')
    pom.element('version', data='1')
    pom.element('packaging', data='pom')
    pom.open('build')
    pom.open('plugins')
    pom.open('plugin')
    pom.element('groupId', data=plugin_group_id)
    pom.element('artifactId', data=plugin_artifact_id)
    pom.element('version', data=plugin_version)
    pom.open('executions')
    for i, spec in enumerate(specs):
        pom.open('execution')
        pom.element('id', data=f'mx-batch-deploy-{i}')
        pom.element('phase', data='validate')
        pom.open('goals')
        pom.element('goal', data=plugin_goal)
        pom.close('goals')
        pom.open('configuration')
        if repo != maven_local_repository():
            pom.element('repositoryId', data=repo.get_maven_id())
            pom.element('url', data=repo.get_url(spec.version))
            pom.element('retryFailedDeploymentCount', data='10')
        pom.element('groupId', data=spec.group_id)
        pom.element('artifactId', data=spec.artifact_id)
        pom.element('version', data=spec.version)
        pom.element('file', data=spec.file_path)
        pom.element('packaging', data=spec.extension)
        if spec.pom_file:
            pom.element('pomFile', data=spec.pom_file)
        else:
            pom.element('generatePom', data='true')
        if spec.src_path:
            pom.element('sources', data=spec.src_path)
        if spec.javadoc_path:
            pom.element('javadoc', data=spec.javadoc_path)
        if spec.extra_files:
            pom.element('files', data=','.join(ef[0] for ef in spec.extra_files))
            pom.element('classifiers', data=','.join(ef[1] for ef in spec.extra_files))
            pom.element('types', data=','.join(ef[2] for ef in spec.extra_files))
        pom.close('configuration')
        pom.close('execution')
    pom.close('executions')
    pom.close('plugin')
    pom.close('plugins')
    pom.close('build')
    pom.close('project')

    with tempfile.NamedTemporaryFile('w', suffix='.pom', delete=False) as tmp:
        tmp.write(pom.xml(indent='  ', newl='\n'))
        return tmp.name


def _run_batched_maven_deploy(specs, repo, settingsXml, dryRun=False):
    if not specs:
        return

    action = 'Installing' if repo == maven_local_repository() else 'Deploying'
    for spec in specs:
        mx.log(f'{action} {spec.group_id}:{spec.artifact_id}...')

    batch_pom = _write_batched_maven_deploy_pom(specs, repo)
    try:
        cmd = _maven_batch_command(settingsXml)
        cmd += ['-f', batch_pom, 'validate']
        if mx._opts.very_verbose or (dryRun and mx._opts.verbose):
            with open(batch_pom, encoding='utf-8') as f:
                mx.log(f.read())
        if dryRun:
            mx.logv(' '.join((shlex.quote(t) for t in cmd)))
        else:
            mx.run_maven(cmd)
    finally:
        os.unlink(batch_pom)


def _create_maven_repo_metadata_file(dists, dryRun, cleanup_paths):
    repo_metadata_xml = mx.XMLDoc()
    repo_metadata_xml.open('suite-revisions')

    includes_primary = False
    loaded_suites = mx.suites()
    for s_ in loaded_suites:
        if s_.vc:
            if s_.name == mx._primary_suite.name:
                includes_primary = True
            commit_timestamp = s_.vc.parent_info(s_.vc_dir)['committer-ts']
            repo_metadata_xml.element('suite', attributes={
                "name": s_.name,
                "revision": s_.vc.parent(s_.vc_dir),
                "date": datetime.utcfromtimestamp(commit_timestamp).isoformat(),
                "kind": s_.vc.kind
            })
    if not includes_primary:
        mx.warn(f"Primary suite '{mx._primary_suite.name}' is not included in the loaded suites. {[s_.name for s_ in loaded_suites]}")

    for d_ in dists:
        for extra_data_tag, extra_data_attributes in d_.extra_suite_revisions_data():
            repo_metadata_xml.element(extra_data_tag, attributes=extra_data_attributes)

    repo_metadata_xml.close('suite-revisions')
    repo_metadata_fd, repo_metadata_name = tempfile.mkstemp(suffix='.xml', text=True)
    cleanup_paths.append(repo_metadata_name)
    repo_metadata = repo_metadata_xml.xml(indent='  ', newl='\n')
    if mx._opts.very_verbose or (dryRun and mx._opts.verbose):
        mx.log(repo_metadata)
    with os.fdopen(repo_metadata_fd, 'w', encoding='utf-8') as f:
        f.write(repo_metadata)
    return repo_metadata_name


def _create_maven_javadoc_jar(dist, generateDummyJavadoc, validateMetadata, cleanup_paths):
    with tempfile.NamedTemporaryFile('w', suffix='.jar', delete=False) as tmpJavadocJar:
        javadocPath = tmpJavadocJar.name
    if getattr(dist, "noMavenJavadoc", False) or generateDummyJavadoc:
        with zipfile.ZipFile(javadocPath, 'w', compression=zipfile.ZIP_DEFLATED) as arc:
            arc.writestr("index.html", "<html><body>No Javadoc</body></html>")
    else:
        projects = [p for p in dist.archived_deps() if p.isJavaProject()]
        tmpDir = tempfile.mkdtemp(prefix='mx-javadoc')
        javadocArgs = ['--base', tmpDir, '--unified', '--projects', ','.join((p.name for p in projects))]
        if dist.javadocType == 'implementation':
            javadocArgs += ['--implementation']
        else:
            assert dist.javadocType == 'api'
        if dist.allowsJavadocWarnings:
            javadocArgs += ['--allow-warnings']
        mx.javadoc(javadocArgs, includeDeps=False, mayBuild=False, quietForNoPackages=True)

        emptyJavadoc = True
        with zipfile.ZipFile(javadocPath, 'w', compression=zipfile.ZIP_DEFLATED) as arc:
            javadocDir = join(tmpDir, 'javadoc')
            for (dirpath, _, filenames) in os.walk(javadocDir):
                for filename in filenames:
                    emptyJavadoc = False
                    src = join(dirpath, filename)
                    dst = os.path.relpath(src, javadocDir)
                    arc.write(src, dst)
        shutil.rmtree(tmpDir)
        if emptyJavadoc:
            os.unlink(javadocPath)
            if validateMetadata == 'full' and dist.suite.getMxCompatibility().validate_maven_javadoc():
                mx.abort(f"Missing javadoc for {dist.name}")
            javadocPath = None
            mx.warn(f'Javadoc for {dist.name} was empty')
    if javadocPath:
        cleanup_paths.append(javadocPath)
    return javadocPath


def _deploy_binary_maven(suite, artifactId, groupId, filePath, version, repo,
                         srcPath=None,
                         description=None,
                         settingsXml=None,
                         extension='jar',
                         dryRun=False,
                         pomFile=None,
                         gpg=False,
                         keyid=None,
                         javadocPath=None,
                         extraFiles=None):
    """
    :type extraFiles: list[(str, str, str)]
    """
    assert exists(filePath), filePath
    assert not srcPath or exists(srcPath), srcPath

    cmd = ['--batch-mode']

    if not mx._opts.verbose:
        cmd.append('--quiet')

    if mx._opts.verbose:
        cmd.append('--errors')

    if mx._opts.very_verbose:
        cmd.append('--debug')

    if settingsXml:
        cmd += ['-s', settingsXml]

    if repo != maven_local_repository():
        cmd += [
            '-DrepositoryId=' + repo.get_maven_id(),
            '-Durl=' + repo.get_url(version)
        ]
        if gpg:
            cmd += ['gpg:sign-and-deploy-file']
        else:
            cmd += ['deploy:deploy-file']
        if keyid:
            cmd += ['-Dgpg.keyname=' + keyid]
    else:
        cmd += ['install:install-file']
        if gpg or keyid:
            mx.abort('Artifact signing not supported for ' + repo.name)

    cmd += [
        '-DgroupId=' + groupId,
        '-DartifactId=' + artifactId,
        '-Dversion=' + version,
        '-Dfile=' + filePath,
        '-Dpackaging=' + extension,
        '-DretryFailedDeploymentCount=10',
    ]
    if pomFile:
        cmd.append('-DpomFile=' + pomFile)
    else:
        cmd.append('-DgeneratePom=true')

    if srcPath:
        cmd.append('-Dsources=' + srcPath)
    if javadocPath:
        cmd.append('-Djavadoc=' + javadocPath)

    if description:
        cmd.append('-Ddescription=' + description)

    if extraFiles:
        cmd.append('-Dfiles=' + ','.join(ef[0] for ef in extraFiles))
        cmd.append('-Dclassifiers=' + ','.join(ef[1] for ef in extraFiles))
        cmd.append('-Dtypes=' + ','.join(ef[2] for ef in extraFiles))

    action = 'Installing' if repo == maven_local_repository() else 'Deploying'
    mx.log(f'{action} {groupId}:{artifactId}...')
    if dryRun:
        mx.logv(' '.join((shlex.quote(t) for t in cmd)))
    else:
        mx.run_maven(cmd)


def _deploy_skip_existing(args, dists, version, repo):
    if args.skip_existing:
        non_existing_dists = []
        for dist in dists:
            if version.endswith('-SNAPSHOT'):
                metadata_append = '-local' if repo == maven_local_repository() else ''
                metadata_url = f"{repo.get_url(version)}/{dist.maven_group_id().replace('.', '/')}/{dist.maven_artifact_id()}/{version}/maven-metadata{metadata_append}.xml"
            else:
                metadata_url = f"{repo.get_url(version)}/{dist.maven_group_id().replace('.', '/')}/{dist.maven_artifact_id()}/{version}/"
            if mx.download_file_exists([metadata_url]):
                mx.log(f'Skip existing {dist.maven_group_id()}:{dist.maven_artifact_id()}')
            else:
                non_existing_dists.append(dist)
        return non_existing_dists
    else:
        return dists


def _deploy_artifact(uploader, dist, path, version, jdk, platform, suite_revisions, snapshot_id, primary_revision, skip_existing=False, dry_run=False):
    assert exists(path), f"{path} does not exist"
    maven_artifact_id = dist.maven_artifact_id(platform)
    dist_metadata = dist.get_artifact_metadata()

    def get_required_metadata(name):
        if name not in dist_metadata or not dist_metadata.get(name):
            mx.abort(f"Artifact metadata for distribution '{dist.name}' must have '{name}'")
        return dist_metadata.get(name)

    distribution_type = get_required_metadata("type")
    edition = get_required_metadata("edition")
    project = get_required_metadata("project")
    extra_metadata = {"suite": dist.suite.name,
                      "distributionName": _map_to_maven_dist_name(dist.name),
                      "artifactId": maven_artifact_id,
                      "groupId": dist.maven_group_id()}
    extra_metadata.update({k: v for k, v in dist_metadata.items() if k not in ["edition", "type", "project"]})

    def dump_metadata_json(data, suffix):
        with tempfile.NamedTemporaryFile(prefix=f"{maven_artifact_id}_{suffix}",
                                         suffix=".json",
                                         delete=False,
                                         mode="w") as file:
            file_name = file.name
            json.dump(data, file)
        return file_name

    suite_revision_file = dump_metadata_json(suite_revisions, "suiteRevisions")
    extra_metadata_file = dump_metadata_json(extra_metadata, "extraMetadata")

    if dist.suite.is_release():
        lifecycle = "release"
        snapshot_id = ""
    else:
        lifecycle = "snapshot"
        snapshot_id = f"-{snapshot_id}"

    cmd = [uploader, "--version", version, "--revision", primary_revision,
           "--suite-revisions", suite_revision_file,
           "--extra-metadata", extra_metadata_file,
           "--lifecycle", lifecycle,
           path,
           f"{project}/{maven_artifact_id}-{version}{snapshot_id}.{dist.remoteExtension()}",
           project]
    if edition:
        cmd.extend(["--edition", edition])
    if distribution_type:
        cmd.extend(["--artifact-type", distribution_type])
    if jdk:
        cmd.extend(["--jdk", jdk])
    if platform:
        cmd.extend(["--platform", platform])
    if skip_existing:
        cmd.append("--skip-existing")
    mx.log(f"Uploading {dist.maven_group_id()}:{dist.maven_artifact_id(platform)}")
    try:
        if not dry_run:
            result = mx.run(cmd)
            mx.log(f"Returned code {result}")
        else:
            mx.log(mx.list_to_cmd_line(cmd))
    finally:
        os.unlink(extra_metadata_file)
        os.unlink(suite_revision_file)


def deploy_binary(args):
    """deploy binaries for the primary suite to remote maven repository

    All binaries must be built first using ``mx build``.
    """
    parser = ArgumentParser(prog='mx deploy-binary')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--only', action='store', help='Limit deployment to these distributions')
    parser.add_argument('--platform-dependent', action='store_true', help='Limit deployment to platform dependent distributions only')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    parser.add_argument('--skip-existing', action='store_true', help='Do not deploy distributions if already in repository')
    parser.add_argument('repository_id', metavar='repository-id', nargs='?', action='store', help='Repository ID used for binary deploy. If none is given, mavens local repository is used instead.')
    parser.add_argument('url', metavar='repository-url', nargs='?', action='store', help='Repository URL used for binary deploy. If no url is given, the repository-id is looked up in suite.py')
    args = parser.parse_args(args)

    if args.all_suites:
        _suites = mx.suites()
    else:
        _suites = mx.primary_or_specific_suites()

    for s in _suites:
        if s.isSourceSuite():
            _deploy_binary(args, s)


def _deploy_binary(args, suite):
    if not suite.getMxCompatibility().supportsLicenses():
        mx.log(f"Not deploying '{suite.name}' because licenses aren't defined")
        return
    if not suite.getMxCompatibility().supportsRepositories():
        mx.log(f"Not deploying '{suite.name}' because repositories aren't defined")
        return
    if not suite.vc:
        mx.abort('Current suite has no version control')

    mx._mvn.check()

    def versionGetter(suite):
        return f'{suite.vc.parent(suite.vc_dir)}-SNAPSHOT'

    dists = suite.dists
    if args.only:
        only = args.only.split(',')
        dists = [d for d in dists if d.name in only or d.qualifiedName() in only]
    if args.platform_dependent:
        dists = [d for d in dists if d.platformDependent]

    mxMetaName = mx._mx_binary_distribution_root(suite.name)
    suite.create_mx_binary_distribution_jar()
    mxMetaJar = suite.mx_binary_distribution_jar_path()
    assert exists(mxMetaJar)
    if args.all_suites:
        dists = [d for d in dists if d.exists()]

    for dist in dists:
        if not dist.exists():
            mx.abort(f"'{dist.name}' is not built, run 'mx build' first")

    platform_dependence = any(d.platformDependent for d in dists)

    if args.url:
        repo = mx.Repository(None, args.repository_id, args.url, args.url, mx.repository(args.repository_id).licenses)
    elif args.repository_id:
        if not suite.getMxCompatibility().supportsRepositories():
            mx.abort(f"Repositories are not supported in {suite.name}'s suite version")
        repo = mx.repository(args.repository_id)
    else:
        repo = maven_local_repository()

    version = versionGetter(suite)
    if not args.only:
        action = 'Installing' if repo == maven_local_repository() else 'Deploying'
        mx.log(f'{action} suite {suite.name} version {version}')
    dists = _deploy_skip_existing(args, dists, version, repo)
    if not dists:
        return

    _maven_deploy_dists(dists, versionGetter, repo, args.settings, dryRun=args.dry_run, deployMapFiles=True)
    if not args.platform_dependent and not args.only:
        _deploy_binary_maven(suite, _map_to_maven_dist_name(mxMetaName), _mavenGroupId(suite.name), mxMetaJar, version, repo, settingsXml=args.settings, dryRun=args.dry_run)

    if not args.all_suites and suite == mx.primary_suite() and suite.vc.kind == 'git' and suite.vc.active_branch(suite.vc_dir) == 'master':
        deploy_branch_name = 'binary'
        platform_dependent_base = deploy_branch_name + '_'
        binary_deployed_ref = platform_dependent_base + mx.Distribution.platformName() if platform_dependence else deploy_branch_name
        deployed_rev = suite.version()
        assert deployed_rev == suite.vc.parent(suite.vc_dir), 'Version mismatch: suite.version() != suite.vc.parent(suite.vc_dir)'

        def try_remote_branch_update(branch_name):
            deploy_item_msg = f"'{branch_name}'-branch to {deployed_rev}"
            mx.log("On master branch: Try setting " + deploy_item_msg)
            retcode = mx.GitConfig.set_branch(suite.vc_dir, branch_name, deployed_rev)
            if retcode:
                mx.log("Updating " + deploy_item_msg + " failed (probably more recent deployment)")
            else:
                mx.log("Successfully updated " + deploy_item_msg)

        try_remote_branch_update(binary_deployed_ref)

        if platform_dependence:
            mx.log("Suite has platform_dependence: Update " + deploy_branch_name)
            platform_dependent_branches = mx.GitConfig.get_matching_branches('origin', platform_dependent_base + '*', vcdir=suite.vc_dir)
            not_on_same_rev = [(branch_name, commit_id) for branch_name, commit_id in platform_dependent_branches.items() if commit_id != deployed_rev]
            if len(not_on_same_rev):
                mx.log("Skip " + deploy_branch_name + " update! The following branches are not yet on " + deployed_rev + ":")
                for branch_name, commit_id in not_on_same_rev:
                    mx.log("  " + branch_name + " --> " + commit_id)
            else:
                try_remote_branch_update(deploy_branch_name)


def _maven_deploy_dists(dists, versionGetter, repo, settingsXml,
                        dryRun=False,
                        validateMetadata='none',
                        gpg=False,
                        keyid=None,
                        generateJavadoc=False,
                        generateDummyJavadoc=False,
                        deployMapFiles=False,
                        deployRepoMetadata=False):
    if repo != maven_local_repository():
        # Non-local deployment requires license checking
        for dist in dists:
            if not dist.theLicense:
                mx.abort(f'Distributions without license are not cleared for upload to {repo.name}: can not upload {dist.name}')
            for distLicense in dist.theLicense:
                if distLicense not in repo.licenses:
                    mx.abort(f'Distribution with {distLicense.name} license are not cleared for upload to {repo.name}: can not upload {dist.name}')

    cleanup_paths = []
    deploy_specs = []
    try:
        repo_metadata_name = _create_maven_repo_metadata_file(dists, dryRun, cleanup_paths) if deployRepoMetadata else None

        for dist in dists:
            for platform in dist.platforms:
                if dist.maven_artifact_id() != dist.maven_artifact_id(platform):
                    full_maven_name = f"{dist.maven_group_id()}:{dist.maven_artifact_id(platform)}"
                    if repo == maven_local_repository():
                        mx.log(f"Installing dummy {full_maven_name}")
                        # Allow installing local dummy platform dependend artifacts for other platforms
                        with tempfile.NamedTemporaryFile('w', suffix='.tar.gz', delete=False) as foreign_platform_dummy_tarball:
                            foreign_platform_dummy_tarball_name = foreign_platform_dummy_tarball.name
                        cleanup_paths.append(foreign_platform_dummy_tarball_name)
                        with mx.Archiver(foreign_platform_dummy_tarball_name, kind='tgz') as arc:
                            arc.add_str(f"Dummy artifact {full_maven_name} for local maven install\n", full_maven_name + ".README", None)
                        deploy_specs.append(_create_maven_deploy_spec(dist.maven_group_id(), dist.maven_artifact_id(platform), foreign_platform_dummy_tarball_name,
                                                                      versionGetter(dist.suite), extension=dist.remoteExtension()))
                    else:
                        mx.logv(f"Skip deploying {full_maven_name}")
                else:
                    pomFile = _tmpPomFile(dist, versionGetter, validateMetadata)
                    cleanup_paths.append(pomFile)
                    if mx._opts.very_verbose or (dryRun and mx._opts.verbose):
                        with open(pomFile, encoding='utf-8') as f:
                            mx.log(f.read())
                    if dist.isJARDistribution():
                        javadocPath = None
                        if generateJavadoc:
                            javadocPath = _create_maven_javadoc_jar(dist, generateDummyJavadoc, validateMetadata, cleanup_paths)

                        extraFiles = []
                        if deployMapFiles and dist.is_stripped():
                            extraFiles.append((dist.strip_mapping_file(), 'proguard', 'map'))
                        if repo_metadata_name:
                            extraFiles.append((repo_metadata_name, 'suite-revisions', 'xml'))

                        jar_to_deploy = dist.path
                        if isinstance(dist.maven, dict):
                            deployment_module_info = dist.maven.get('moduleInfo')
                            if deployment_module_info:
                                jdk = mx.get_jdk(dist.maxJavaCompliance())
                                if jdk.javaCompliance <= '1.8':
                                    mx.warn('Distribution with "moduleInfo" sub-attribute of the "maven" attribute deployed with JAVA_HOME <= 8', context=dist)
                                else:
                                    jmd = as_java_module(dist, jdk)
                                    if not jmd.alternatives:
                                        mx.abort('"moduleInfo" sub-attribute of the "maven" attribute specified but distribution does not contain any "moduleInfo:*" attributes', context=dist)
                                    alt_jmd = jmd.alternatives.get(deployment_module_info)
                                    if not alt_jmd:
                                        mx.abort(f'"moduleInfo" sub-attribute of the "maven" attribute specifies non-existing "moduleInfo:{deployment_module_info}" attribute', context=dist)
                                    jar_to_deploy = alt_jmd.jarpath

                        pushed_file = dist.prePush(jar_to_deploy)
                        if pushed_file != jar_to_deploy:
                            cleanup_paths.append(pushed_file)
                        if getattr(dist, "noMavenSources", False):
                            with tempfile.NamedTemporaryFile('w', suffix='.jar', delete=False) as tmpSourcesJar:
                                pushed_src_file = tmpSourcesJar.name
                            with zipfile.ZipFile(pushed_src_file, 'w', compression=zipfile.ZIP_DEFLATED) as arc:
                                with StringIO() as license_file_content:
                                    license_ids = dist.theLicense
                                    if not license_ids:
                                        license_ids = dist.suite.defaultLicense
                                    for resolved_license in mx.get_license(license_ids):
                                        print(f'{resolved_license.name}    {resolved_license.url}\n', file=license_file_content)
                                    arc.writestr("LICENSE", license_file_content.getvalue())
                        else:
                            pushed_src_file = dist.prePush(dist.sourcesPath)
                        if pushed_src_file != dist.sourcesPath:
                            cleanup_paths.append(pushed_src_file)
                        deploy_specs.append(_create_maven_deploy_spec(dist.maven_group_id(), dist.maven_artifact_id(), pushed_file,
                                                                      versionGetter(dist.suite),
                                                                      srcPath=pushed_src_file,
                                                                      extension=dist.remoteExtension(),
                                                                      pomFile=pomFile,
                                                                      javadocPath=javadocPath,
                                                                      extraFiles=extraFiles))
                    elif dist.isTARDistribution() or dist.isZIPDistribution():
                        extraFiles = []
                        if repo_metadata_name:
                            extraFiles.append((repo_metadata_name, 'suite-revisions', 'xml'))
                        pushed_file = dist.prePush(dist.path)
                        if pushed_file != dist.path:
                            cleanup_paths.append(pushed_file)
                        deploy_specs.append(_create_maven_deploy_spec(dist.maven_group_id(), dist.maven_artifact_id(), pushed_file,
                                                                      versionGetter(dist.suite),
                                                                      extension=dist.remoteExtension(),
                                                                      pomFile=pomFile,
                                                                      extraFiles=extraFiles))
                    elif dist.isPOMDistribution():
                        extraFiles = []
                        if repo_metadata_name:
                            extraFiles.append((repo_metadata_name, 'suite-revisions', 'xml'))
                        deploy_specs.append(_create_maven_deploy_spec(dist.maven_group_id(), dist.maven_artifact_id(), pomFile,
                                                                      versionGetter(dist.suite),
                                                                      extension=dist.remoteExtension(),
                                                                      pomFile=pomFile,
                                                                      extraFiles=extraFiles))
                    else:
                        mx.abort_or_warn('Unsupported distribution: ' + dist.name, dist.suite.getMxCompatibility().maven_deploy_unsupported_is_error())

        if not gpg and len(deploy_specs) > 1:
            _run_batched_maven_deploy(deploy_specs, repo, settingsXml, dryRun=dryRun)
        else:
            for spec in deploy_specs:
                _deploy_binary_maven(None, spec.artifact_id, spec.group_id, spec.file_path, spec.version, repo,
                                     srcPath=spec.src_path,
                                     settingsXml=settingsXml,
                                     extension=spec.extension,
                                     dryRun=dryRun,
                                     pomFile=spec.pom_file,
                                     gpg=gpg, keyid=keyid,
                                     javadocPath=spec.javadoc_path,
                                     extraFiles=spec.extra_files)
    finally:
        for path in reversed(cleanup_paths):
            try:
                os.unlink(path)
            except OSError:
                pass


def _deploy_dists(uploader, dists, version_getter, snapshot_id, primary_revision, skip_existing=False, dry_run=False):
    related_suites_revisions = [{"suite": s_.name, "revision": s_.vc.parent(s_.vc_dir)} for s_ in mx.suites() if s_.vc]
    if mx._opts.very_verbose or (dry_run and mx._opts.verbose):
        mx.log(related_suites_revisions)
    jdk_version = mx.get_jdk(tag='default').javaCompliance.value
    for dist in dists:
        to_deploy = dist.path
        if not dist.isTARDistribution() and not dist.isZIPDistribution() and not dist.isLayoutJARDistribution():
            mx.abort('Unsupported distribution: ' + dist.name)

        pushed_file = dist.prePush(to_deploy)
        try:
            _deploy_artifact(dist=dist, path=pushed_file, version=version_getter(dist.suite), uploader=uploader,
                             jdk=str(jdk_version),
                             platform=mx.Distribution.platformName().replace("_", "-"),
                             suite_revisions=related_suites_revisions,
                             skip_existing=skip_existing,
                             dry_run=dry_run,
                             primary_revision=primary_revision,
                             snapshot_id=snapshot_id)
        finally:
            if pushed_file != to_deploy:
                os.unlink(pushed_file)

def _match_tags(dist, tags):
    maven = getattr(dist, 'maven', False)
    maven_tag = {'default'}
    if isinstance(maven, dict) and 'tag' in maven:
        maven_tag = maven['tag']
        if isinstance(maven_tag, str):
            maven_tag = {maven_tag}
        elif isinstance(maven_tag, list):
            maven_tag = set(maven_tag)
        else:
            mx.abort('Maven tag must be str or list[str]', context=dist)
    return any(tag in maven_tag for tag in tags)

def _file_name_match(dist, names):
    return any(fnmatch.fnmatch(dist.name, n) or fnmatch.fnmatch(dist.qualifiedName(), n) for n in names)

def _dist_matcher(dist, tags, all_distributions, only, skip, all_distribution_types):
    if tags is not None and not _match_tags(dist, tags):
        return False
    if all_distributions:
        return True
    if not (dist.isJARDistribution() or dist.isPOMDistribution()) and not all_distribution_types:
        return False
    if only is not None:
        return _file_name_match(dist, only)
    if skip is not None and _file_name_match(dist, skip):
        return False
    return getattr(dist, 'maven', False) and not dist.is_test_distribution()

def _dist_matcher_all(dist, tags, only, skip):
    if tags is not None and not _match_tags(dist, tags):
        return False
    if only is not None:
        return _file_name_match(dist, only)
    if skip is not None and _file_name_match(dist, skip):
        return False
    return True

def maven_deploy(args):
    """deploy jars for the primary suite to remote maven repository

    All binaries must be built first using 'mx build'.
    """
    parser = ArgumentParser(prog='mx maven-deploy')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    parser.add_argument('--only', action='store', help='Comma-separated list of globs of distributions to be deployed')
    parser.add_argument('--skip', action='store', help='Comma-separated list of globs of distributions not to be deployed')
    parser.add_argument('--skip-existing', action='store_true', help='Do not deploy distributions if already in repository')
    parser.add_argument('--validate', help='Validate that maven metadata is complete enough for publication', default='compat', choices=['none', 'compat', 'full'])
    javadoc_parser = parser.add_mutually_exclusive_group()
    javadoc_parser.add_argument('--suppress-javadoc', action='store_true', help='Suppress javadoc generation and deployment')
    javadoc_parser.add_argument('--dummy-javadoc', action='store_true', help='Generate and deploy dummy javadocs, as if every distribution has `"noMavenJavadoc": True`')
    parser.add_argument('--all-distribution-types', help='Include all distribution types. By default, only JAR distributions are included', action='store_true')
    parser.add_argument('--all-distributions', help='Include all distributions, regardless of the maven flags.', action='store_true')
    version_parser = parser.add_mutually_exclusive_group()
    version_parser.add_argument('--version-string', action='store', help='Provide custom version string for deployment')
    version_parser.add_argument('--version-suite', action='store', help='The name of a vm suite that provides the version string for deployment')
    parser.add_argument('--licenses', help='Comma-separated list of licenses that are cleared for upload. Only used if no url is given. Otherwise licenses are looked up in suite.py', default='')
    parser.add_argument('--gpg', action='store_true', help='Sign files with gpg before deploying')
    parser.add_argument('--gpg-keyid', help='GPG keyid to use when signing files (implies --gpg)', default=None)
    parser.add_argument('--tags', help='Comma-separated list of tags to match in the maven metadata of the distribution. When left unspecified, no filtering is done. The default tag is \'default\'', default=None)
    parser.add_argument('--with-suite-revisions-metadata', help='Deploy suite revisions metadata file', action='store_true')
    parser.add_argument('repository_id', metavar='repository-id', nargs='?', action='store', help='Repository ID used for Maven deploy')
    parser.add_argument('url', metavar='repository-url', nargs='?', action='store', help='Repository URL used for Maven deploy, if no url is given, the repository-id is looked up in suite.py')
    args = parser.parse_args(args)

    if args.gpg_keyid and not args.gpg:
        args.gpg = True
        mx.logv('Implicitly setting gpg to true since a keyid was specified')

    mx._mvn.check()

    def versionGetter(_suite):
        if args.version_string:
            return args.version_string
        s = mx.suite(args.version_suite) if args.version_suite is not None else _suite
        return s.release_version(snapshotSuffix='SNAPSHOT')

    if args.all_suites:
        _suites = mx.suites()
    else:
        _suites = mx.primary_or_specific_suites()

    tags = args.tags.split(',') if args.tags is not None else None
    only = args.only.split(',') if args.only is not None else None
    skip = args.skip.split(',') if args.skip is not None else None

    has_deployed_dist = False

    for s in _suites:
        dists = [d for d in s.dists if _dist_matcher(d, tags, args.all_distributions, only, skip, args.all_distribution_types)]
        if args.url:
            licenses = mx.get_license(args.licenses.split(','))
            repo = mx.Repository(None, args.repository_id, args.url, args.url, licenses)
        elif args.repository_id:
            if not s.getMxCompatibility().supportsRepositories():
                mx.abort(f"Repositories are not supported in {s.name}'s suite version")
            repo = mx.repository(args.repository_id)
        else:
            repo = maven_local_repository()

        dists = _deploy_skip_existing(args, dists, versionGetter(s), repo)
        if not dists and not args.all_suites:
            mx.warn("No distribution to deploy in " + s.name)
            continue

        for dist in dists:
            if not dist.exists():
                mx.abort(f"'{dist.name}' is not built, run 'mx build' first")

        generateJavadoc = None if args.suppress_javadoc else s.getMxCompatibility().mavenDeployJavadoc()

        _maven_deploy_dists(dists, versionGetter, repo, args.settings,
                            dryRun=args.dry_run,
                            validateMetadata=args.validate,
                            gpg=args.gpg,
                            keyid=args.gpg_keyid,
                            generateJavadoc=generateJavadoc,
                            generateDummyJavadoc=args.dummy_javadoc,
                            deployRepoMetadata=args.with_suite_revisions_metadata)
        has_deployed_dist = True
    if not has_deployed_dist:
        mx.abort("No distribution was deployed!")

def deploy_artifacts(args):
    """Uses provided custom uploader to deploy primary suite to a remote repository
    The upload script needs to respect the following interface :
        path
        artifact-name
        project
        --artifact-type     : base, installable, standalone ...
        --version
        --jdk               : java major version
        --edition           : ee or ce
        --extra-metadata    : accepts a json file with any extra metadata related to the artifact
        --suite-revisions   : accepts a json file in this format [{"suite": str, "revision":  valid sha1}]
        --revision          : hash of the sources for the artifact (valid sha1)
        --lifecycle         : one of 'snapshot' or 'release'
        --platform          : <os>-<arch>
    All binaries must be built first using 'mx build'.
    """
    parser = ArgumentParser(prog='mx deploy-artifacts')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    parser.add_argument('--only', action='store', help='Comma-separated list of globs of distributions to be deployed')
    parser.add_argument('--skip', action='store', help='Comma-separated list of globs of distributions not to be deployed')
    parser.add_argument('--skip-existing', action='store_true', help='Do not deploy distributions if already in repository')
    parser.add_argument('--version-string', action='store', help='Provide custom version string for deployment')
    parser.add_argument('--tags', help='Comma-separated list of tags to match in the maven metadata of the distribution. When left unspecified, no filtering is done. The default tag is \'default\'', default=None)
    parser.add_argument('--uploader', action='store', help='Uploader')
    args = parser.parse_args(args)

    primary_revision = mx._primary_suite.vc.parent(mx._primary_suite.vc_dir)
    snapshot_id = f"{primary_revision[:10]}-{uuid.uuid4()}"

    def versionGetter(suite):
        if args.version_string:
            return args.version_string
        return suite.release_version(snapshotSuffix='SNAPSHOT')

    if args.all_suites:
        _suites = mx.suites()
    else:
        _suites = mx.primary_or_specific_suites()
    tags = args.tags.split(',') if args.tags is not None else None
    only = args.only.split(',') if args.only is not None else None
    skip = args.skip.split(',') if args.skip is not None else None
    has_deployed_dist = False
    for s in _suites:
        dists = [d for d in s.dists if _dist_matcher_all(dist=d, tags=tags, only=only, skip=skip) and d.get_artifact_metadata() is not None]
        if not dists and not args.all_suites:
            mx.warn("No distribution to deploy in " + s.name)
            continue
        for dist in dists:
            if not dist.exists():
                mx.abort(f"'{dist.name}' is not built, run 'mx build' first")

        mx.log(f'Deploying {s.name} distributions for version {versionGetter(s)}')
        _deploy_dists(dists=dists, version_getter=versionGetter, primary_revision=primary_revision, snapshot_id=snapshot_id, uploader=args.uploader, skip_existing=args.skip_existing, dry_run=args.dry_run)
        has_deployed_dist = True
    if not has_deployed_dist:
        mx.abort("No distribution was deployed!")

def maven_url(args):
    _artifact_url(args, 'mx maven-url', 'mx maven-deploy', lambda s: s.release_version('SNAPSHOT'))

def binary_url(args):
    def snapshot_version(suite):
        if suite.vc:
            return f'{suite.vc.parent(suite.vc_dir)}-SNAPSHOT'
        else:
            mx.abort('binary_url requires suite to be under a vcs repository')
    _artifact_url(args, 'mx binary-url', 'mx deploy-binary', snapshot_version)

def _artifact_url(args, prog, deploy_prog, snapshot_version_fun):
    parser = ArgumentParser(prog=prog)
    parser.add_argument('repository_id', action='store', help='Repository name')
    parser.add_argument('dist_name', action='store', help='Distribution name')
    parser.add_argument('--no-digest', '--no-sha1', action='store_false', dest='digest', help='Do not display the URL of the digest file')
    args = parser.parse_args(args)

    repo = mx.repository(args.repository_id)
    dist = mx.distribution(args.dist_name)

    group_id = dist.maven_group_id()
    artifact_id = dist.maven_artifact_id()
    snapshot_version = snapshot_version_fun(dist.suite)
    extension = dist.remoteExtension()

    maven_repo = MavenRepo(repo.get_url(snapshot_version))
    snapshot = maven_repo.getSnapshot(group_id, artifact_id, snapshot_version)

    if not snapshot:
        url = maven_repo.getSnapshotUrl(group_id, artifact_id, snapshot_version)
        mx.abort(f'Version {snapshot_version} not found for {group_id}:{artifact_id} ({url})\nNote that the binary must have been deployed with `{deploy_prog}`')
    build = snapshot.getCurrentSnapshotBuild()
    try:
        url, digest_url = build.getSubArtifact(extension)
        print(url)
        if args.digest:
            print(digest_url)
    except MavenSnapshotArtifact.NonUniqueSubArtifactException:
        mx.abort(f'Multiple {extension}s found for {dist.remoteName()} in snapshot {build.version} in repository {maven_repo.repourl}')

class MavenConfig:
    def __init__(self):
        self.has_maven = None
        self.missing = 'no mvn executable found'

    def check(self, abortOnError=True):
        if self.has_maven is None:
            try:
                mx.run_maven(['--version'], out=lambda e: None)
                self.has_maven = True
            except OSError:
                self.has_maven = False
                mx.warn(self.missing)

        if not self.has_maven:
            if abortOnError:
                mx.abort(self.missing)
            else:
                mx.warn(self.missing)

        return self if self.has_maven else None


def mvn_local_install(group_id, artifact_id, path, version, repo=None):
    if not exists(path):
        mx.abort('File ' + path + ' does not exists')
    repoArgs = ['-Dmaven.repo.local=' + repo] if repo else []
    mx.run_maven(['install:install-file', '-DgroupId=' + group_id, '-DartifactId=' + artifact_id, '-Dversion=' +
               version, '-Dpackaging=jar', '-Dfile=' + path, '-DcreateChecksum=true'] + repoArgs)


def maven_install(args):
    """install the primary suite in a local maven repository for testing"""
    parser = ArgumentParser(prog='mx maven-install')
    parser.add_argument('--no-checks', action='store_true', help='checks on status are disabled')
    parser.add_argument('--test', action='store_true', help='print info about JARs to be installed')
    parser.add_argument('--repo', action='store', help='path to local Maven repository to install to')
    parser.add_argument('--only', action='store', help='comma separated set of distributions to install')
    parser.add_argument('--version-string', action='store', help='Provide custom version string for installment')
    parser.add_argument('--all-suites', action='store_true', help='Deploy suite and the distributions it depends on in other suites')
    args = parser.parse_args(args)

    mx._mvn.check()
    if args.all_suites:
        _suites = mx.suites()
    else:
        _suites = [mx.primary_suite()]
    for s in _suites:
        nolocalchanges = args.no_checks or not s.vc or s.vc.can_push(s.vc_dir, strict=False)
        version = args.version_string if args.version_string else s.vc.parent(s.vc_dir)
        releaseVersion = s.release_version(snapshotSuffix='SNAPSHOT')
        arcdists = []
        only = args.only.split(',') if args.only is not None else None
        dists = [d for d in s.dists if _dist_matcher(d, None, False, only, None, False)]
        for dist in dists:
            # ignore non-exported dists
            if not dist.internal and not dist.name.startswith('COM_ORACLE') and hasattr(dist, 'maven') and dist.maven:
                arcdists.append(dist)

        mxMetaName = mx._mx_binary_distribution_root(s.name)
        s.create_mx_binary_distribution_jar()
        mxMetaJar = s.mx_binary_distribution_jar_path()
        if not args.test:
            if nolocalchanges:
                mvn_local_install(_mavenGroupId(s.name), _map_to_maven_dist_name(mxMetaName), mxMetaJar, version, args.repo)
            else:
                print('Local changes found, skipping install of ' + version + ' version')
            mvn_local_install(_mavenGroupId(s.name), _map_to_maven_dist_name(mxMetaName), mxMetaJar, releaseVersion, args.repo)
            for dist in arcdists:
                if nolocalchanges:
                    mvn_local_install(dist.maven_group_id(), dist.maven_artifact_id(), dist.path, version, args.repo)
                mvn_local_install(dist.maven_group_id(), dist.maven_artifact_id(), dist.path, releaseVersion, args.repo)
        else:
            print('jars to deploy manually for version: ' + version)
            print('name: ' + _map_to_maven_dist_name(mxMetaName) + ', path: ' + os.path.relpath(mxMetaJar, s.dir))
            for dist in arcdists:
                print('name: ' + dist.maven_artifact_id() + ', path: ' + os.path.relpath(dist.path, s.dir))
