#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2019, Oracle and/or its affiliates. All rights reserved.
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
r"""
mx is a command line tool for managing the development of Java code organized as suites of projects.

"""
from __future__ import print_function

import os
import zipfile
import time
import re

from os.path import join, exists, basename, dirname
from argparse import ArgumentTypeError
from stat import S_IMODE

import mx
import mx_subst

class JARDistribution(mx.Distribution, mx.ClasspathDependency):
    """
    Represents a jar file built from the class files and resources defined by a set of
    `JavaProject`s and Java libraries plus an optional zip containing the Java source files
    corresponding to the class files.

    :param Suite suite: the suite in which the distribution is defined
    :param str name: the name of the distribution which must be unique across all suites
    :param list stripConfigFileNames: names of stripping configurations that are located in `<mx_dir>/proguard/` and suffixed with `.proguard`
    :param list stripMappingFileNames: names of stripping maps that are located in `<mx_dir>/proguard/` and suffixed with `.map`
    :param str | None subDir: a path relative to `suite.dir` in which the IDE project configuration for this distribution is generated
    :param str path: the path of the jar file created for this distribution. If this is not an absolute path,
           it is interpreted to be relative to `suite.dir`.
    :param str | None sourcesPath: the path of the zip file created for the source files corresponding to the class files of this distribution.
           If this is not an absolute path, it is interpreted to be relative to `suite.dir`.
    :param list deps: the `JavaProject` and `Library` dependencies that are the root sources for this distribution's jar
    :param str | None mainClass: the class name representing application entry point for this distribution's executable jar. This
           value (if not None) is written to the ``Main-Class`` header in the jar's manifest.
    :param list excludedLibs: libraries whose contents should be excluded from this distribution's jar
    :param list distDependencies: the `JARDistribution` dependencies that must be on the class path when this distribution
           is on the class path (at compile or run time)
    :param str | None javaCompliance:
    :param bool platformDependent: specifies if the built artifact is platform dependent
    :param str | None theLicense: license applicable when redistributing the built artifact of the distribution
    :param str javadocType: specifies if the javadoc generated for this distribution should include implementation documentation
           or only API documentation. Accepted values are "implementation" and "API".
    :param bool allowsJavadocWarnings: specifies whether warnings are fatal when javadoc is generated
    :param bool maven:
    :param dict[str, str] | None manifestEntries: Entries for the `META-INF/MANIFEST.MF` file.
    """
    def __init__(self, suite, name, subDir, path, sourcesPath, deps, mainClass, excludedLibs, distDependencies, javaCompliance, platformDependent, theLicense,
                 javadocType="implementation", allowsJavadocWarnings=False, maven=True, stripConfigFileNames=None,
                 stripMappingFileNames=None, manifestEntries=None, **kwArgs):
        assert manifestEntries is None or isinstance(manifestEntries, dict)
        mx.Distribution.__init__(self, suite, name, deps + distDependencies, excludedLibs, platformDependent, theLicense, **kwArgs)
        mx.ClasspathDependency.__init__(self, **kwArgs)
        self.subDir = subDir
        if path:
            path = mx_subst.path_substitutions.substitute(path)
            self._path = mx._make_absolute(path.replace('/', os.sep), self.suite.dir)
        else:
            self._path = None
        if sourcesPath == '<none>':
            # `<none>` is used in the `suite.py` is used to specify that there should be no source zip.
            self._sources_path = None
        elif sourcesPath:
            sources_path = mx_subst.path_substitutions.substitute(sourcesPath)
            self._sources_path = mx._make_absolute(sources_path.replace('/', os.sep), self.suite.dir)
        else:
            self._sources_path = '<uninitialized>'

        self.archiveparticipants = []
        self.mainClass = mainClass
        self.javaCompliance = mx.JavaCompliance(javaCompliance) if javaCompliance else None
        self.definedAnnotationProcessors = []
        self.javadocType = javadocType
        self.allowsJavadocWarnings = allowsJavadocWarnings
        self.maven = maven
        self.manifestEntries = dict([]) if manifestEntries is None else manifestEntries
        if stripConfigFileNames:
            self.stripConfig = [join(suite.mxDir, 'proguard', stripConfigFileName + '.proguard') for stripConfigFileName in stripConfigFileNames]
        else:
            self.stripConfig = None
        if stripMappingFileNames:
            self.stripMapping = [join(suite.mxDir, 'proguard', stripMappingFileName + '.map') for stripMappingFileName in stripMappingFileNames]
        else:
            self.stripMapping = []
        if self.is_stripped():
            # Make this a build dependency to avoid concurrency issues that can arise
            # when the library is lazily resolved by build tasks (which can be running
            # concurrently).
            self.buildDependencies.append("mx:PROGUARD_6_1_1")

    def post_init(self):
        # paths are initialized late to be able to figure out the max jdk
        if self._path is None:
            self._path = mx._make_absolute(self._default_path(), self.suite.dir)

        if self._sources_path == '<uninitialized>':
            # self._sources_path== '<uninitialized>' denotes that no sourcesPath was specified in `suite.py` and we should generate one.
            self._sources_path = mx._make_absolute(self._default_source_path(), self.suite.dir)

        assert self.path.endswith(self.localExtension())

    def default_source_filename(self):
        return mx._map_to_maven_dist_name(self.name) + '.src.zip'

    def _default_source_path(self):
        return join(dirname(self._default_path()), self.default_source_filename())

    def _extra_artifact_discriminant(self):
        if self.suite.isBinarySuite() or not self.suite.getMxCompatibility().jarsUseJDKDiscriminant():
            return ''
        compliance = self._compliance_for_build()
        if compliance:
            return 'jdk{}'.format(compliance)
        return ''

    def _compliance_for_build(self):
        # This JAR will contain class files up to maxJavaCompliance
        compliance = self.maxJavaCompliance()
        if compliance is not None and compliance < '9' and mx.get_module_name(self):
            # if it is modular, bump compliance to 9+ to get a module-info file
            jdk9 = mx.get_jdk('9+', cancel='No module-info will be generated for modular JAR distributions')
            if jdk9:
                compliance = max(compliance, jdk9.javaCompliance)
        return compliance

    @property
    def path(self):
        if self.is_stripped():
            return self._stripped_path()
        else:
            return self.original_path()

    def _stripped_path(self):
        """
        Gets the path to the ProGuard stripped version of the jar. Due to a limitation in ProGuard
        handling of multi-release jars (https://sourceforge.net/p/proguard/bugs/671), the stripped
        jar is specific to the default JDK (i.e. defined by JAVA_HOME/--java-home).
        """
        assert self._path is not None, self.name
        res = getattr(self, '.stripped_path', None)
        if res is None:
            jdk = mx.get_jdk(tag='default')
            res = join(mx.ensure_dir_exists(join(dirname(self._path), 'stripped', str(jdk.javaCompliance))), basename(self._path))
            setattr(self, '.stripped_path', res)
        return res

    def original_path(self):
        assert self._path is not None, self.name
        return self._path

    @property
    def sourcesPath(self):
        assert self._sources_path != '<uninitialized>'
        return self._sources_path

    def maxJavaCompliance(self):
        """:rtype : JavaCompliance"""
        assert not self.suite.isBinarySuite()
        if not hasattr(self, '.maxJavaCompliance'):
            javaCompliances = [p.javaCompliance for p in self.archived_deps() if p.isJavaProject()]
            if self.javaCompliance is not None:
                javaCompliances.append(self.javaCompliance)
            if len(javaCompliances) > 0:
                setattr(self, '.maxJavaCompliance', max(javaCompliances))
            else:
                setattr(self, '.maxJavaCompliance', None)
        return getattr(self, '.maxJavaCompliance')

    def paths_to_clean(self):
        paths = [self.original_path(), self._stripped_path(), self.strip_mapping_file()]
        jdk = mx.get_jdk(tag='default')
        if jdk.javaCompliance >= '9':
            info = mx.get_java_module_info(self)
            if info:
                _, pickle_path, _ = info  # pylint: disable=unpacking-non-sequence
                paths.append(pickle_path)
        return paths

    def is_stripped(self):
        return mx._opts.strip_jars and self.stripConfig is not None

    def set_archiveparticipant(self, archiveparticipant):
        """
        Adds an object that participates in the `make_archive` method of this distribution.

        :param archiveparticipant: an object for which the following methods, if defined, will be called by `make_archive`:

            __opened__(arc, srcArc, services)
                Called when archiving starts. The `arc` and `srcArc` Archiver objects are for writing to the
                binary and source jars for the distribution. The `services` dict is for collating the files
                that will be written to ``META-INF/services`` in the binary jar. It is a map from service names
                to a list of providers for the named service. If services should be versioned, an integer can be used
                as a key and the value is a map from service names to a list of providers for this version.
            __add__(arcname, contents)
                Submits an entry for addition to the binary archive (via the `zf` ZipFile field of the `arc` object).
                Returns True if this object claims responsibility for adding/eliding `contents` to/from the archive,
                False otherwise (i.e., the caller must take responsibility for the entry).
            __addsrc__(arcname, contents)
                Same as `__add__` except that it targets the source archive.
            __closing__()
                Called just before the `services` are written to the binary archive and both archives are
                written to their underlying files.
        """
        if archiveparticipant not in self.archiveparticipants:
            if not hasattr(archiveparticipant, '__opened__'):
                mx.abort(str(archiveparticipant) + ' must define __opened__')
            self.archiveparticipants.append(archiveparticipant)
        else:
            mx.warn('registering archive participant ' + str(archiveparticipant) + ' for ' + str(self) + ' twice')

    def origin(self):
        return mx.Dependency.origin(self)

    def classpath_repr(self, resolve=True):
        if resolve and not exists(self.path):
            if exists(self.original_path()):
                jdk = mx.get_jdk(tag='default')
                msg = "The Java {} stripped jar for {} does not exist: {}{}".format(jdk.javaCompliance, self, self.path, os.linesep)
                msg += "This might be solved by running: mx --java-home={} --strip build --dependencies={}".format(jdk.home, self)
                mx.abort(msg)
            msg = "The jar for {} does not exist: {}{}".format(self, self.path, os.linesep)
            msg += "This might be solved by running: mx build --dependencies={}".format(self)
            mx.abort(msg)
        return self.path

    def get_ide_project_dir(self):
        """
        Gets the directory in which the IDE project configuration for this distribution is generated.
        """
        if self.subDir:
            return join(self.suite.dir, self.subDir, self.name + '.dist')
        else:
            return join(self.suite.dir, self.name + '.dist')

    def make_archive(self, javac_daemon=None):
        """
        Creates the jar file(s) defined by this JARDistribution.
        """
        if isinstance(self.suite, mx.BinarySuite):
            return

        # are sources combined into main archive?
        unified = self.original_path() == self.sourcesPath
        snippetsPattern = None
        if hasattr(self.suite, 'snippetsPattern'):
            snippetsPattern = re.compile(self.suite.snippetsPattern)

        versioned_meta_inf_re = re.compile(r'META-INF/versions/([1-9][0-9]*)/META-INF/')

        services = {}
        manifestEntries = self.manifestEntries.copy()
        with mx.Archiver(self.original_path()) as arc:
            with mx.Archiver(None if unified else self.sourcesPath, compress=True) as srcArcRaw:
                srcArc = arc if unified else srcArcRaw

                for a in self.archiveparticipants:
                    a.__opened__(arc, srcArc, services)

                def participants__add__(arcname, contents, addsrc=False):
                    """
                    Calls the __add__ or __addsrc__ method on `self.archiveparticipants`, ensuring at most one participant claims
                    responsibility for adding/omitting `contents` under the name `arcname` to/from the archive.

                    :param str arcname: name in archive for `contents`
                    :params str contents: byte array to write to the archive under `arcname`
                    :return: True if a participant claimed responsibility, False otherwise
                    """
                    claimer = None
                    for a in self.archiveparticipants:
                        method = getattr(a, '__add__' if not addsrc else '__addsrc__', None)
                        if method:
                            if method(arcname, contents):
                                if claimer:
                                    mx.abort('Archive participant ' + str(a) + ' cannot claim responsibility for ' + arcname + ' in ' +
                                          arc.path + ' as it was already claimed by ' + str(claimer))
                                claimer = a
                    return claimer is not None

                class ArchiveWriteGuard:
                    """
                    A scope for adding an entry to an archive. The addition should only be performed
                    if the scope object is not None when entered:
                    ```
                    with ArchiveWriteGuard(...) as guard:
                        if guard: <add entry to archive
                    ```
                    """
                    def __init__(self, path, zf, arcname, source, source_zf=None):
                        self.path = path
                        self.zf = zf
                        self.source_zf = source_zf
                        self.arcname = arcname
                        self.source = source
                        self._can_write = False

                    def __enter__(self):
                        arcname = self.arcname
                        source = self.source
                        if os.path.basename(arcname).startswith('.'):
                            mx.logv('Excluding dotfile: ' + source)
                            return None
                        elif arcname == "META-INF/MANIFEST.MF":
                            if self.source_zf:
                                # Do not inherit the manifest from other jars
                                mx.logv('Excluding META-INF/MANIFEST.MF from ' + source)
                                return None
                        if not hasattr(self.zf, '_provenance'):
                            self.zf._provenance = {}
                        existingSource = self.zf._provenance.get(arcname, None)
                        if existingSource and existingSource != source:
                            if arcname[-1] not in (os.path.sep, '/'):
                                if self.source_zf and self.source_zf.read(arcname) == self.zf.read(arcname):
                                    mx.logv(self.path + ': file ' + arcname + ' is already present\n  new: ' + source + '\n  old: ' + existingSource)
                                else:
                                    mx.warn(self.path + ': avoid overwrite of ' + arcname + '\n  new: ' + source + '\n  old: ' + existingSource)
                            return None
                        self._can_write = True
                        return self

                    def __exit__(self, exc_type, exc_value, traceback):
                        if self._can_write:
                            if self.arcname in self.zf.namelist():
                                self.zf._provenance[self.arcname] = self.source

                def addFromJAR(jarPath):
                    with zipfile.ZipFile(jarPath, 'r') as source_zf:
                        for info in source_zf.infolist():
                            arcname = info.filename
                            if arcname == 'module-info.class':
                                mx.logv(jarPath + ' contains ' + arcname + '. It will not be included in ' + arc.path)
                            elif arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/':
                                service = arcname[len('META-INF/services/'):]
                                assert '/' not in service
                                services.setdefault(service, []).extend(mx._decode(source_zf.read(arcname)).splitlines())
                            else:
                                with ArchiveWriteGuard(self.original_path(), arc.zf, arcname, jarPath + '!' + arcname, source_zf=source_zf) as guard:
                                    if guard:
                                        contents = source_zf.read(arcname)
                                        if not participants__add__(arcname, contents):
                                            if versioned_meta_inf_re.match(arcname):
                                                mx.warn("META-INF resources can not be versioned ({} from {}). The resulting JAR will be invalid.".format(arcname, jarPath))
                                            # The JDK's ZipInputStream will fail to read files with a data descriptor written by python's zipfile
                                            info.flag_bits &= ~0x08
                                            arc.zf.writestr(info, contents)

                def addFile(outputDir, relpath, archivePrefix, arcnameCheck=None, includeServices=False):
                    arcname = join(archivePrefix, relpath).replace(os.sep, '/')
                    assert arcname[-1] != '/'
                    if arcnameCheck is not None and not arcnameCheck(arcname):
                        return
                    if relpath.startswith(join('META-INF', 'services')):
                        if includeServices:
                            service = basename(relpath)
                            assert dirname(relpath) == join('META-INF', 'services')
                            m = versioned_meta_inf_re.match(arcname)
                            if m:
                                service_version = int(m.group(1))
                                services_dict = services.setdefault(service_version, {})
                            else:
                                services_dict = services
                            with mx.open(join(outputDir, relpath), 'r') as fp:
                                services_dict.setdefault(service, []).extend([provider.strip() for provider in fp.readlines()])
                    else:
                        if snippetsPattern and snippetsPattern.match(relpath):
                            return
                        source = join(outputDir, relpath)
                        with ArchiveWriteGuard(self.original_path(), arc.zf, arcname, source) as guard:
                            if guard:
                                with mx.open(source, 'rb') as fp:
                                    contents = fp.read()
                                if not participants__add__(arcname, contents):
                                    if versioned_meta_inf_re.match(arcname):
                                        mx.warn("META-INF resources can not be versioned ({}). The resulting JAR will be invalid.".format(source))
                                    info = zipfile.ZipInfo(arcname, time.localtime(mx.getmtime(source))[:6])
                                    info.compress_type = arc.zf.compression
                                    info.external_attr = S_IMODE(mx.stat(source).st_mode) << 16
                                    arc.zf.writestr(info, contents)

                def addSrcFromDir(srcDir, archivePrefix='', arcnameCheck=None):
                    for root, _, files in os.walk(srcDir):
                        relpath = root[len(srcDir) + 1:]
                        for f in files:
                            if f.endswith('.java'):
                                arcname = join(archivePrefix, relpath, f).replace(os.sep, '/')
                                if arcnameCheck is None or arcnameCheck(arcname):
                                    with ArchiveWriteGuard(self.original_path(), srcArc.zf, arcname, join(root, f)) as guard:
                                        if guard:
                                            with mx.open(join(root, f), 'rb') as fp:
                                                contents = fp.read()
                                            if not participants__add__(arcname, contents, addsrc=True):
                                                info = zipfile.ZipInfo(arcname, time.localtime(mx.getmtime(join(root, f)))[:6])
                                                info.compress_type = srcArc.zf.compression
                                                info.external_attr = S_IMODE(mx.stat(join(root, f)).st_mode) << 16
                                                srcArc.zf.writestr(info, contents)

                if self.mainClass:
                    if 'Main-Class' in manifestEntries:
                        mx.abort("Main-Class is defined both as the 'mainClass': '" + self.mainClass + "' argument and in 'manifestEntries' as "
                              + manifestEntries['Main-Class'] + " of the " + self.name + " distribution. There should be only one definition.")
                    manifestEntries['Main-Class'] = self.mainClass

                # Overlay projects whose JDK version is less than 9 must be processed before the overlayed projects
                # as the overlay classes must be added to the jar instead of the overlayed classes. Overlays for
                # JDK 9 or later use the multi-release jar layout.
                head = [d for d in self.archived_deps() if d.isJavaProject() and d.javaCompliance.value < 9 and hasattr(d, 'overlayTarget')]
                tail = [d for d in self.archived_deps() if d not in head]

                # Map from JDK 8 or earlier overlays to the projects that define them
                overlays = {}

                for dep in head + tail:
                    if hasattr(dep, "doNotArchive") and dep.doNotArchive:
                        mx.logv('[' + self.original_path() + ': ignoring project ' + dep.name + ']')
                        continue
                    if self.theLicense is not None and set(self.theLicense or []) < set(dep.theLicense or []):
                        if dep.suite.getMxCompatibility().supportsLicenses() and self.suite.getMxCompatibility().supportsLicenses():
                            report = mx.abort
                        else:
                            report = mx.warn
                        depLicense = [l.name for l in dep.theLicense] if dep.theLicense else ['??']
                        selfLicense = [l.name for l in self.theLicense] if self.theLicense else ['??']
                        report('Incompatible licenses: distribution {} ({}) can not contain {} ({})'.format(self.name, ', '.join(selfLicense), dep.name, ', '.join(depLicense)))
                    if dep.isLibrary() or dep.isJARDistribution():
                        if dep.isLibrary():
                            l = dep
                            # optional libraries and their dependents should already have been removed
                            assert not l.optional or l.is_available()
                            # merge library jar into distribution jar
                            mx.logv('[' + self.original_path() + ': adding library ' + l.name + ']')
                            jarPath = l.get_path(resolve=True)
                            jarSourcePath = l.get_source_path(resolve=True)
                        elif dep.isJARDistribution():
                            mx.logv('[' + self.original_path() + ': adding distribution ' + dep.name + ']')
                            jarPath = dep.path
                            jarSourcePath = dep.sourcesPath
                        else:
                            raise mx.abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))
                        if jarPath:
                            addFromJAR(jarPath)
                        if srcArc.zf and jarSourcePath:
                            with zipfile.ZipFile(jarSourcePath, 'r') as source_zf:
                                for arcname in source_zf.namelist():
                                    with ArchiveWriteGuard(self.original_path(), srcArc.zf, arcname, jarPath + '!' + arcname, source_zf=source_zf) as guard:
                                        if guard:
                                            contents = source_zf.read(arcname)
                                            if not participants__add__(arcname, contents, addsrc=True):
                                                srcArc.zf.writestr(arcname, contents)
                    elif dep.isMavenProject():
                        mx.logv('[' + self.original_path() + ': adding jar from Maven project ' + dep.name + ']')
                        addFromJAR(dep.classpath_repr())
                        for srcDir in dep.source_dirs():
                            addSrcFromDir(srcDir)
                    elif dep.isJavaProject():
                        p = dep
                        javaCompliance = self.maxJavaCompliance()
                        if javaCompliance:
                            if p.javaCompliance > javaCompliance:
                                mx.abort("Compliance level doesn't match: Distribution {0} requires {1}, but {2} is {3}.".format(self.name, javaCompliance, p.name, p.javaCompliance), context=self)

                        mx.logv('[' + self.original_path() + ': adding project ' + p.name + ']')
                        outputDir = p.output_dir()

                        archivePrefix = p.archive_prefix() if hasattr(p, 'archive_prefix') else ''
                        mrjVersion = getattr(p, 'multiReleaseJarVersion', None)
                        is_overlay = False
                        if mrjVersion is not None:
                            if p.javaCompliance.value < 9:
                                mx.abort('Project with "multiReleaseJarVersion" attribute must have javaCompliance >= 9', context=p)
                            if archivePrefix:
                                mx.abort("Project cannot have a 'multiReleaseJarVersion' attribute if it has an 'archivePrefix' attribute", context=p)
                            try:
                                mrjVersion = mx._parse_multireleasejar_version(mrjVersion)
                            except ArgumentTypeError as e:
                                mx.abort(str(e), context=p)
                            archivePrefix = 'META-INF/versions/{}/'.format(mrjVersion)
                            manifestEntries['Multi-Release'] = 'true'
                        elif hasattr(p, 'overlayTarget'):
                            if p.javaCompliance.value > 8:
                                if p.suite.getMxCompatibility().automatic_overlay_distribution_deps:
                                    mx.abort('Project with an "overlayTarget" attribute and javaCompliance >= 9 must also have a "multiReleaseJarVersion" attribute', context=p)
                                mx.abort('Project with an "overlayTarget" attribute must have javaCompliance < 9', context=p)
                            is_overlay = True
                            if archivePrefix:
                                mx.abort("Project cannot have a 'overlayTarget' attribute if it has an 'archivePrefix' attribute", context=p)

                        def overlay_check(arcname):
                            if is_overlay:
                                if arcname in overlays:
                                    mx.abort('Overlay for {} is defined by more than one project: {} and {}'.format(arcname, p, overlays[arcname]))
                                overlays[arcname] = p
                                return True
                            else:
                                return arcname not in overlays

                        def addClasses(archivePrefix, includeServices):
                            for root, _, files in os.walk(outputDir):
                                reldir = root[len(outputDir) + 1:]
                                for f in files:
                                    relpath = join(reldir, f)
                                    addFile(outputDir, relpath, archivePrefix, arcnameCheck=overlay_check, includeServices=includeServices)

                        addClasses(archivePrefix, includeServices=True)
                        if srcArc.zf:
                            sourceDirs = p.source_dirs()
                            if p.source_gen_dir():
                                sourceDirs.append(p.source_gen_dir())
                            for srcDir in sourceDirs:
                                addSrcFromDir(srcDir, archivePrefix, arcnameCheck=overlay_check)

                        if p.javaCompliance.value <= 8:
                            for ver in p.javaCompliance._values():
                                if ver > 8:
                                    # Make a multi-release-jar versioned copy of the class files
                                    # if compliance includes 8 or less and a version higher than 8.
                                    # Anything below that version will pick up the class files in the
                                    # root directory of the jar.
                                    if mx.get_jdk(str(mx.JavaCompliance(ver)), cancel='probing'):
                                        archivePrefix = 'META-INF/versions/{}/'.format(ver)
                                        addClasses(archivePrefix, includeServices=False)
                                    break

                    elif dep.isArchivableProject():
                        mx.logv('[' + self.original_path() + ': adding archivable project ' + dep.name + ']')
                        archivePrefix = dep.archive_prefix()
                        outputDir = dep.output_dir()
                        for f in dep.getResults():
                            relpath = dep.get_relpath(f, outputDir)
                            addFile(outputDir, relpath, archivePrefix)
                    elif dep.isClasspathDependency():
                        mx.logv('[' + self.original_path() + ': adding classpath ' + dep.name + ']')
                        jarPath = dep.classpath_repr(resolve=True)
                        addFromJAR(jarPath)
                    else:
                        mx.abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))

                if len(manifestEntries) != 0:
                    if 'Manifest-Version' not in manifestEntries:
                        manifest = 'Manifest-Version: 1.0' + '\n'
                    else:
                        manifest = 'Manifest-Version: ' + manifestEntries['Manifest-Version'] + '\n'
                        manifestEntries.pop('Manifest-Version')

                    for manifestKey, manifestValue in manifestEntries.items():
                        manifest = manifest + manifestKey + ': ' + manifestValue + '\n'

                    arc.zf.writestr("META-INF/MANIFEST.MF", manifest)
                for a in self.archiveparticipants:
                    if hasattr(a, '__closing__'):
                        a.__closing__()

                # accumulate services
                services_versions = sorted([v for v in services if isinstance(v, int)])
                if services_versions:
                    acummulated_services = {n: set(p) for n, p in services.items() if isinstance(n, str)}
                    for v in services_versions:
                        for service, providers in services[v].items():
                            providers_set = frozenset(providers)
                            accumulated_providers = acummulated_services.setdefault(service, set())
                            missing = accumulated_providers - providers_set
                            accumulated_providers.update(providers_set)
                            if missing:
                                mx.warn("Adding {} for {} at version {}".format(missing, service, v))
                                services[v][service] = frozenset(accumulated_providers)

                def add_service_providers(service, providers, archive_prefix=''):
                    arcname = archive_prefix + 'META-INF/services/' + service
                    # Convert providers to a set before printing to remove duplicates
                    arc.zf.writestr(arcname, '\n'.join(frozenset(providers)) + '\n')

                for service_or_version, providers in services.items():
                    if isinstance(service_or_version, int):
                        services_version = service_or_version
                        for service, providers_ in providers.items():
                            add_service_providers(service, providers_, 'META-INF/_versions/' + str(services_version) + '/')
                    else:
                        add_service_providers(service_or_version, providers)

        self.notify_updated()

        compliance = self._compliance_for_build()
        if compliance is not None and compliance >= '9':
            jdk = mx.get_jdk(compliance)
            jmd = mx.make_java_module(self, jdk, javac_daemon)
            if jmd:
                setattr(self, '.javaModule', jmd)
                dependency_file = self._jmod_build_jdk_dependency_file()
                with mx.open(dependency_file, 'w') as fp:
                    fp.write(jdk.home)

        if self.is_stripped():
            self.strip_jar()

    _strip_map_file_suffix = '.map'
    _strip_cfg_deps_file_suffix = '.conf.d'

    def strip_mapping_file(self):
        return self._stripped_path() + JARDistribution._strip_map_file_suffix

    def strip_config_dependency_file(self):
        return self._stripped_path() + JARDistribution._strip_cfg_deps_file_suffix

    def strip_jar(self):
        assert mx.get_opts().strip_jars, "Only works under the flag --strip-jars"

        jdk = mx.get_jdk(tag='default')
        if jdk.javaCompliance > '13':
            mx.abort('Cannot strip {} - ProGuard does not yet support JDK {}'.format(self, jdk.javaCompliance))

        mx.logv('Stripping {}...'.format(self.name))
        jdk9_or_later = jdk.javaCompliance >= '9'

        # add config files from projects
        assert all((os.path.isabs(f) for f in self.stripConfig))
        # add mapping files
        assert all((os.path.isabs(f) for f in self.stripMapping))

        proguard = ['-jar', mx.library('PROGUARD_6_1_1').get_path(resolve=True)]

        prefix = [
            '-dontusemixedcaseclassnames', # https://sourceforge.net/p/proguard/bugs/762/
            '-adaptclassstrings',
            '-adaptresourcefilecontents META-INF/services/*',
            '-adaptresourcefilenames META-INF/services/*',
            '-renamesourcefileattribute stripped',
            '-keepattributes Exceptions,InnerClasses,Signature,Deprecated,SourceFile,LineNumberTable,RuntimeVisible*Annotations,EnclosingMethod,AnnotationDefault',

            # options for incremental stripping
            '-dontoptimize -dontshrink -useuniqueclassmembernames']

        # add configs
        for file_name in self.stripConfig:
            with mx.open(file_name, 'r') as fp:
                prefix.extend((l.strip() for l in fp.readlines()))

        def _create_derived_file(base_file, suffix, lines):
            derived_file = mx._derived_path(base_file, suffix)
            with mx.open(derived_file, 'w') as fp:
                for line in lines:
                    print(line, file=fp)
            return derived_file

        # add mappings of all stripped dependencies (must be one file)
        input_maps = self.stripMapping + [d.strip_mapping_file() for d in mx.classpath_entries(self, includeSelf=False) if d.isJARDistribution() and d.is_stripped()]
        if input_maps:
            input_maps_file = mx._derived_path(self.path, '.input_maps')
            with mx.open(input_maps_file, 'w') as fp_out:
                for file_name in input_maps:
                    with mx.open(file_name, 'r') as fp_in:
                        fp_out.write(fp_in.read())
            prefix += ['-applymapping ' + input_maps_file]

        # Create flattened input jar
        flattened_jar = mx._derived_path(self.path, '', prefix='flattened_')
        flattened_entries = {}
        with zipfile.ZipFile(self.original_path(), 'r') as in_zf:
            compression = in_zf.compression
            versions = {}
            for info in in_zf.infolist():
                if not info.filename.startswith('META-INF/versions/'):
                    if info.filename.startswith('META-INF/services/') and jdk9_or_later and self.get_declaring_module_name():
                        # Omit JDK 8 style service descriptors when flattening for a 9+ module
                        pass
                    else:
                        flattened_entries[info.filename] = (info, in_zf.read(info))

            for info in in_zf.infolist():
                if info.filename.startswith('META-INF/versions/'):
                    if jdk9_or_later:
                        import mx_javamodules
                        m = mx_javamodules._versioned_re.match(info.filename)
                        if m:
                            version = int(m.group(1))
                            unversioned_name = m.group(2)
                            if version <= jdk.javaCompliance.value:
                                contents = in_zf.read(info)
                                info.filename = unversioned_name
                                versions.setdefault(version, {})[unversioned_name] = (info, contents)
                            else:
                                # Omit versioned resource whose version is too high
                                pass
                    else:
                        # Omit versioned resources when flattening for JDK 8
                        pass
                elif info.filename.startswith('META-INF/services/') and jdk9_or_later:
                    # Omit JDK 8 style service descriptors when flattening for 9+
                    pass
                else:
                    flattened_entries[info.filename] = (info, in_zf.read(info))
            if versions:
                for version, entries in sorted(versions.items()):
                    flattened_entries.update(entries)

        with mx.SafeFileCreation(flattened_jar) as sfc:
            with zipfile.ZipFile(sfc.tmpPath, 'w', compression) as out_zf:
                for name, ic in sorted(flattened_entries.items()):
                    info, contents = ic
                    assert info.filename == name
                    out_zf.writestr(info, contents)

        if jdk9_or_later:
            prefix += [
            '-keepattributes Module*',

            # https://sourceforge.net/p/proguard/bugs/704/#d392
            '-keep class module-info',

            # Must keep package names due to https://sourceforge.net/p/proguard/bugs/763/
            '-keeppackagenames **'
            ]

        if mx.get_opts().very_verbose:
            prefix += ['-verbose']
        elif not mx.get_opts().verbose:
            prefix += ['-dontnote **']

        # https://sourceforge.net/p/proguard/bugs/671/#56b4
        jar_filter = '(!META-INF/versions/**,!module-info.class)'

        if not jdk9_or_later:
            libraryjars = mx.classpath(self, includeSelf=False, includeBootClasspath=True, jdk=jdk, unique=True, ignoreStripped=True).split(os.pathsep)
            include_file = _create_derived_file(self.path, '.proguard', prefix + [
                '-injars ' + flattened_jar,
                '-outjars ' + self.path,
                '-libraryjars ' + os.pathsep.join((e + jar_filter for e in libraryjars)),
                '-printmapping ' + self.strip_mapping_file(),
            ])
            strip_command = proguard + ['-include', include_file]

            mx.run_java(strip_command, jdk=jdk)
            with mx.open(self.strip_config_dependency_file(), 'w') as f:
                f.writelines((l + os.linesep for l in self.stripConfig))
        else:
            cp_entries = mx.classpath_entries(self, includeSelf=False)
            self_jmd = mx.as_java_module(self, jdk) if mx.get_java_module_info(self) else None
            dep_modules = frozenset(e for e in cp_entries if e.isJARDistribution() and mx.get_java_module_info(e))
            dep_module_names = frozenset((mx.get_java_module_info(e)[0] for e in dep_modules))

            dep_jmds = frozenset((mx.as_java_module(e, jdk) for e in cp_entries if e.isJARDistribution() and mx.get_java_module_info(e)))
            dep_jars = mx.classpath(self, includeSelf=False, includeBootClasspath=False, jdk=jdk, unique=True, ignoreStripped=True).split(os.pathsep)

            # Add jmods from the JDK except those overridden by dependencies
            jdk_jmods = [m.get_jmod_path(respect_stripping=False) for m in jdk.get_modules() if m.name not in dep_module_names]

            # Make stripped jar
            include_file = _create_derived_file(self.path, '.proguard', prefix + [
                '-injars ' + flattened_jar,
                '-outjars ' + self.path,
                '-libraryjars ' + os.pathsep.join((e + jar_filter for e in dep_jars + jdk_jmods)),
                '-printmapping ' + self.path + JARDistribution._strip_map_file_suffix,
            ])

            strip_commands = [proguard + ['-include', include_file]]
            if self_jmd:
                # Make stripped jmod
                stripped_jmod = self_jmd.get_jmod_path(respect_stripping=True)
                dep_jmods = [jmd.get_jmod_path(respect_stripping=True) for jmd in dep_jmds]

                include_file = _create_derived_file(stripped_jmod, '.proguard', prefix + [
                        '-injars ' + self_jmd.get_jmod_path(respect_stripping=False),
                        '-outjars ' + stripped_jmod,
                        '-libraryjars ' + os.pathsep.join((e + jar_filter for e in dep_jmods + jdk_jmods)),
                        '-printmapping ' + stripped_jmod + JARDistribution._strip_map_file_suffix,
                ])

                strip_commands.append(proguard + ['-include', include_file])
            for command in strip_commands:
                mx.run_java(command, jdk=jdk)
            with mx.open(self.strip_config_dependency_file(), 'w') as f:
                f.writelines((l + os.linesep for l in self.stripConfig))

    def remoteName(self, platform=None):
        base_name = super(JARDistribution, self).remoteName(platform=platform)
        if self.is_stripped():
            return base_name + "_stripped"
        else:
            return base_name

    def getBuildTask(self, args):
        return mx.JARArchiveTask(args, self)

    def exists(self):
        return exists(self.path) and not self.sourcesPath or exists(self.sourcesPath) #pylint: disable=consider-using-ternary

    def remoteExtension(self):
        return 'jar'

    def localExtension(self):
        return 'jar'

    def getArchivableResults(self, use_relpath=True, single=False):
        yield self.path, self.default_filename()
        if not single:
            if self.sourcesPath:
                yield self.sourcesPath, self.default_source_filename()
            if self.is_stripped():
                yield self.strip_mapping_file(), self.default_filename() + JARDistribution._strip_map_file_suffix

    def _jmod_build_jdk_dependency_file(self):
        """
        Gets the path to the file recording the JAVA_HOME of the JDK last used to
        build the modular jar for this distribution.
        """
        return self.original_path() + '.jdk'

    def needsUpdate(self, newestInput):
        res = mx._needsUpdate(newestInput, self.path)
        if res:
            return res
        if self.sourcesPath:
            res = mx._needsUpdate(newestInput, self.sourcesPath)
            if res:
                return res
        if self.suite.isBinarySuite():
            return None
        compliance = self._compliance_for_build()
        if compliance is not None and compliance >= '9':
            info = mx.get_java_module_info(self)
            if info:
                _, pickle_path, _ = info  # pylint: disable=unpacking-non-sequence
                res = mx._needsUpdate(newestInput, pickle_path)
                if res:
                    return res
                res = mx._needsUpdate(self.original_path(), pickle_path)
                if res:
                    return res
                # Rebuild the jmod file if different JDK used previously
                jdk = mx.get_jdk(compliance)
                dependency_file = self._jmod_build_jdk_dependency_file()
                if exists(dependency_file):
                    with mx.open(dependency_file) as fp:
                        last_build_jdk = fp.read()
                    if last_build_jdk != jdk.home:
                        return 'build JDK changed from {} to {}'.format(last_build_jdk, jdk.home)
        if self.is_stripped():
            previous_strip_configs = []
            dependency_file = self.strip_config_dependency_file()
            if exists(dependency_file):
                with mx.open(dependency_file) as f:
                    previous_strip_configs = (l.rstrip('\r\n') for l in f.readlines())
            if set(previous_strip_configs) != set(self.stripConfig):
                return 'strip config files changed'
            for f in self.stripConfig:
                ts = mx.TimeStampFile(f)
                if ts.isNewerThan(self.path):
                    return '{} is newer than {}'.format(ts, self.path)
        return None

    def get_declaring_module_name(self):
        return mx.get_module_name(self)
