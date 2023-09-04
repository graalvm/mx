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

import os
import shutil
import zipfile
import time
import re
import pickle

from os.path import join, exists, basename, dirname, isdir, islink
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
    :param bool useModulePath: put this distribution and all its dependencies on the module-path.
    :param bool compress: compress jar entries of the main jar with deflate. The source zip is always compressed.
    :param dict[str, str] | None manifestEntries: Entries for the `META-INF/MANIFEST.MF` file.
    """
    def __init__(self, suite, name, subDir, path, sourcesPath, deps, mainClass, excludedLibs, distDependencies, javaCompliance, platformDependent, theLicense,
                 javadocType="implementation", allowsJavadocWarnings=False, maven=True, useModulePath=False, stripConfigFileNames=None,
                 stripMappingFileNames=None, manifestEntries=None, alwaysStrip=None, compress=False, **kwArgs):
        assert manifestEntries is None or isinstance(manifestEntries, dict)
        mx.Distribution.__init__(self, suite, name, deps + distDependencies, excludedLibs, platformDependent, theLicense, **kwArgs)
        mx.ClasspathDependency.__init__(self, use_module_path=useModulePath, **kwArgs)
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
        self.compress = compress
        self.manifestEntries = dict([]) if manifestEntries is None else manifestEntries
        if stripConfigFileNames and alwaysStrip:
            mx.abort('At most one of the "strip" and "alwaysStrip" properties can be used on a distribution', context=self)
        if stripConfigFileNames:
            self.stripConfig = [join(suite.mxDir, 'proguard', stripConfigFileName + '.proguard') for stripConfigFileName in stripConfigFileNames]
            self.strip_mode = 'optional'
        elif alwaysStrip:
            self.stripConfig = [join(suite.mxDir, 'proguard', stripConfigFileName + '.proguard') for stripConfigFileName in alwaysStrip]
            self.strip_mode = 'always'
        else:
            self.strip_mode = 'none'
            self.stripConfig = None
        if stripMappingFileNames:
            self.stripMapping = [join(suite.mxDir, 'proguard', stripMappingFileName + '.map') for stripMappingFileName in stripMappingFileNames]
        else:
            self.stripMapping = []
        if self.is_stripped() and mx.get_opts().proguard_cp is None:
            # Make this a build dependency to avoid concurrency issues that can arise
            # when the library is lazily resolved by build tasks (which can be running
            # concurrently).
            self.buildDependencies.extend((l.suite.name + ':' + l.name for l in mx.classpath_entries('PROGUARD_BASE_' + self.suite.getMxCompatibility().proguard_libs()['BASE'])))
        if useModulePath and self.get_declaring_module_name() is None:
            mx.abort('The property useModulePath is set to True but the distribution does not contain a module specification. Add a "moduleInfo" attribute with a name to resolve this.', context=self)

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
            return f'jdk{compliance}'
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
        paths = [
            self.original_path(),
            self.sourcesPath,
            self.original_path() + _staging_dir_suffix,
            self.sourcesPath + _staging_dir_suffix,
            self._stripped_path(),
            self.strip_mapping_file(),
            self._config_save_file(),
        ]
        jdk = mx.get_jdk(tag='default')
        if jdk.javaCompliance >= '9':
            info = mx.get_java_module_info(self)
            if info:
                _, pickle_path, _ = info  # pylint: disable=unpacking-non-sequence
                paths.append(pickle_path)
        return paths

    def is_stripped(self):
        return self.stripConfig is not None and (mx._opts.strip_jars or self.strip_mode == 'always')

    def set_archiveparticipant(self, archiveparticipant):
        """
        Adds an object that participates in the `make_archive` method of this distribution.

        :param archiveparticipant: an object for which the following methods, if defined, will be called by `make_archive`:

            __opened__(arc, srcArc, services)
                Called when archiving starts. The `arc` and `srcArc` values are objects that have a `path` field
                which is the path of the binary and source jars respectively for the distribution. The `services`
                dict is for collating the files that will be written to ``META-INF/services`` in the binary jar.
                It is a map from service names to a list of providers for the named service. If services should
                be versioned, an integer can be used as a key instead and the value is a map from service names to a list
                of providers for the version denoted by the integer.

            __process__(arcname, contents_supplier, is_source)
                Notifies of an entry destined for the binary (`is_source` is False) or source archive (`is_source` is True).
                Returns True if this object consumes the contents supplied by `contents_supplier`,
                False if the caller should add the contents to the relevant archive.

            # Deprecated: Define __process__ instead
            __add__(arcname, contents)
                Notifies of an entry that is about to be added to the binary archive.
                Returns True if this object consumes `contents`,
                False if the caller should add `contents` to the binary archive.

            # Deprecated: Define __process__ instead
            __addsrc__(arcname, contents)
                Notifies of an entry that is about to be added to the source archive.
                Returns True if this object consumes `contents`,
                False if the caller should add `contents` to the source archive.

            __closing__()
                Called just before the `services` are written to the binary archive and both archives are finalized.
                If the archive participant wants to add extra entries to the archive, it returns a 2-tuple
                with each value being a dict of (arcname, contents) describing the extra entries.
        """
        ap_type = archiveparticipant.__class__.__name__
        if ap_type == 'FastRArchiveParticipant':
            # This archive participant deletes directories that are assumed
            # to have been already added to fastr-release.jar. It is removed
            # in FastR by GR-30568 but this workaround allows mx to keep working
            # with older versions.
            mx.warn(f'Ignoring registration of {ap_type} object for {self}')
            return

        if archiveparticipant not in self.archiveparticipants:
            if not hasattr(archiveparticipant, '__opened__'):
                mx.abort(str(archiveparticipant) + ' must define __opened__')
            _patch_archiveparticipant(archiveparticipant.__class__)
            self.archiveparticipants.append(archiveparticipant)
        else:
            mx.warn('registering archive participant ' + str(archiveparticipant) + ' for ' + str(self) + ' twice')

    def origin(self):
        return mx.Dependency.origin(self)

    def classpath_repr(self, resolve=True):
        if resolve and not exists(self.path):
            if exists(self.original_path()):
                jdk = mx.get_jdk(tag='default')
                msg = f"The Java {jdk.javaCompliance} stripped jar for {self} does not exist: {self.path}{os.linesep}"
                msg += f"This might be solved by running: mx --java-home={jdk.home} --strip build --dependencies={self}"
                mx.abort(msg)
            msg = f"The jar for {self} does not exist: {self.path}{os.linesep}"
            msg += f"This might be solved by running: mx build --dependencies={self}"
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
        exploded = self._is_exploded()

        bin_archive = _Archive(self, self.original_path(), exploded, zipfile.ZIP_DEFLATED if self.compress else zipfile.ZIP_STORED)
        src_archive = _Archive(self, self.sourcesPath, exploded, zipfile.ZIP_DEFLATED) if not unified else bin_archive

        bin_archive.clean()
        src_archive.clean()

        stager = _ArchiveStager(bin_archive, src_archive, exploded)

        # GR-31142
        latest_bin_archive = join(self.suite.get_output_root(False, False), "dists", os.path.basename(bin_archive.path))
        _stage_file_impl(bin_archive.path, latest_bin_archive)

        with mx.open(self._config_save_file(), 'w') as fp:
            fp.write(self._config_as_json())

        self.notify_updated()
        compliance = self._compliance_for_build()
        if compliance is not None and compliance >= '9':
            jdk = mx.get_jdk(compliance)
            jmd = mx.make_java_module(self, jdk, stager.bin_archive, javac_daemon=javac_daemon)
            if jmd:
                setattr(self, '.javaModule', jmd)
                dependency_file = self._jmod_build_jdk_dependency_file()
                with mx.open(dependency_file, 'w') as fp:
                    fp.write(jdk.home)

        if self.is_stripped():
            self.strip_jar()

    # See https://docs.oracle.com/en/java/javase/16/docs/api/java.instrument/java/lang/instrument/package-summary.html
    _javaagent_manifest_attributes = ('Premain-Class', 'Agent-Class')

    def _can_be_exploded(self):
        """
        Determines if `self` can have its artifact be a directory instead of a jar.
        This is true if `self` does not:
         - Define an annotation processor. Eclipse only supports annotation processors packaged as jars.
         - Define an Java agent since Java agents can only be deployed as jars.
        """
        if 'Premain-Class' in self.manifestEntries or 'Agent-Class' in self.manifestEntries or self.definedAnnotationProcessors:
            return False
        return True

    def _is_exploded(self):
        """
        Determines if the result of `self.make_archive` is (or would be) a directory instead of a jar.
        """
        return self._can_be_exploded() and _use_exploded_build()

    _strip_map_file_suffix = '.map'
    _strip_cfg_deps_file_suffix = '.conf.d'

    def strip_mapping_file(self):
        return self._stripped_path() + JARDistribution._strip_map_file_suffix

    def strip_config_dependency_file(self):
        return self._stripped_path() + JARDistribution._strip_cfg_deps_file_suffix

    def strip_jar(self):
        assert self.is_stripped()

        def _abort(*args, **kwargs):
            mx.log_error(f'No JDK compatible with ProGuard found')
            mx.abort(*args, **kwargs)

        max_java_compliance = self.maxJavaCompliance().value
        proguard_jdk_version = self.suite.getMxCompatibility().proguard_supported_jdk_version()
        if max_java_compliance > proguard_jdk_version and mx.get_opts().proguard_cp is None:
            mx.abort(f'Cannot strip {self} - ProGuard does not yet support JDK {max_java_compliance}')
        _range = f'{max_java_compliance}..{proguard_jdk_version}' if max_java_compliance != proguard_jdk_version else str(max_java_compliance)
        jdk = mx.get_jdk(_range, abortCallback=_abort)

        mx.logv(f'Stripping {self.name}...')
        jdk9_or_later = jdk.javaCompliance >= '9'

        # add config files from projects
        assert all((os.path.isabs(f) for f in self.stripConfig))
        # add mapping files
        assert all((os.path.isabs(f) for f in self.stripMapping))

        proguard = ['-cp', _get_proguard_cp(self.suite), 'proguard.ProGuard']

        prefix = [
            '-dontusemixedcaseclassnames', # https://sourceforge.net/p/proguard/bugs/762/
            '-adaptclassstrings',
            '-adaptresourcefilecontents META-INF/services/*',
            '-adaptresourcefilenames META-INF/services/*',
            '-renamesourcefileattribute stripped',
            '-keepattributes Exceptions,InnerClasses,Signature,Deprecated,SourceFile,LineNumberTable,RuntimeVisible*Annotations,EnclosingMethod,AnnotationDefault',
            '-keepclassmembernames class ** { static boolean $assertionsDisabled; }',

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
                dep_jmods = [jmd.get_jmod_path(respect_stripping=False) for jmd in dep_jmds]
                dep_lib_modules = [module_lib.lib.get_path(resolve=True) for module_lib in self_jmd.modulepath if module_lib.lib]

                include_file = _create_derived_file(stripped_jmod, '.proguard', prefix + [
                        '-injars ' + self_jmd.get_jmod_path(respect_stripping=False),
                        '-outjars ' + stripped_jmod,
                        '-libraryjars ' + os.pathsep.join((e + jar_filter for e in dep_lib_modules + dep_jmods + jdk_jmods)),
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

    def _config_save_file(self) -> str:
        """
        Gets the path to the file saving :meth:`_config_as_json`.
        """
        return self.original_path() + ".json"

    def _config_as_json(self) -> str:
        """
        Creates a sorted json dump of attributes that trigger a rebuild when they're changed (see :meth:`needsUpdate`).
        """
        config = {}

        def add_attribute(key, value):
            """
            Adds an attribute to the config dict and makes sure no entry is overwritten.

            If entries are overwritten, the overwritten attribute is ignored when checking for updates.
            """
            assert key not in config, f"Duplicate value in distribution config: {key}"
            config[key] = value

        # The `exclude` list can change the jar file contents and needs to trigger a rebuild
        add_attribute("excludedLibs", list(map(str, self.excludedLibs)))

        compliance = self._compliance_for_build()
        if compliance is not None and compliance >= '9':
            if mx.get_java_module_info(self):
                # Module info change triggers a rebuild.
                for name in dir(self):
                    if name == 'moduleInfo' or name.startswith('moduleInfo:'):
                        add_attribute(name, getattr(self, name))

        import json
        return json.dumps(config, sort_keys=True, indent=2)

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

        if exists(self.path):
            # Re-build if switching to/from exploded builds
            if _use_exploded_build() != isdir(self.path):
                if self._can_be_exploded():
                    return 'MX_BUILD_EXPLODED value has changed'

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
                jdk = mx.get_jdk(compliance)

                # Rebuild the jmod file if different JDK used previously
                dependency_file = self._jmod_build_jdk_dependency_file()
                if exists(dependency_file):
                    with mx.open(dependency_file) as fp:
                        last_build_jdk = fp.read()
                    if last_build_jdk != jdk.home:
                        return f'build JDK changed from {last_build_jdk} to {jdk.home}'
                try:
                    with open(pickle_path, 'rb') as fp:
                        pickle.load(fp)
                except ValueError as e:
                    return f'Bad or incompatible module pickle: {e}'

        # Rebuild if the saved config file changed or doesn't exist
        config_file = self._config_save_file()
        if exists(config_file):
            current_config = self._config_as_json()
            with mx.open(config_file) as fp:
                saved_config = fp.read()
            if current_config != saved_config:
                import difflib
                mx.log(f'{self} distribution config changed:' + os.linesep + ''.join(difflib.unified_diff(saved_config.splitlines(True), current_config.splitlines(True))))
                return f'{config_file} changed'
        else:
            return f'{config_file} does not exist'

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
                    return f'{ts} is newer than {self.path}'
        return None

    def get_declaring_module_name(self):
        return mx.get_module_name(self)

def _get_proguard_cp(suite=mx.primary_suite()):
    """
    Gets the class path required to run ProGuard (either the main app or the retrace app).
    """
    proguard_cp = mx.get_opts().proguard_cp
    if not proguard_cp:
        proguard_cp = mx.classpath(['PROGUARD_' + name + '_' + version for name, version in suite.getMxCompatibility().proguard_libs().items()])
    return proguard_cp

class _StagingGuard:
    """
    A context manager implementing a predicate for whether a file should be staged.
    The staging should only be performed if the context manager does not return None when entered:
    ```
    with _StagingGuard(entry) as guard:
        if guard:
            <stage_file>
    ```
    """
    def __init__(self, entry):
        self.entry = entry
        self.entries = entry.archive.entries
        self._can_write = False

    def __enter__(self):
        arcname = self.entry.name
        origin = self.entry.origin
        if os.path.basename(arcname).startswith('.'):
            mx.logv('Excluding dotfile: ' + origin)
            return None
        elif arcname == "META-INF/MANIFEST.MF":
            if self.entry.origin_is_archive:
                # Do not inherit the manifest from other jars
                mx.logv('Excluding META-INF/MANIFEST.MF from ' + origin)
                return None
        existing_entry = self.entries.get(arcname, None)
        if existing_entry and existing_entry.origin != origin:
            entry = existing_entry.resolve_origin_conflict(self.entry)
            if entry is None:
                return
            if entry is existing_entry:
                mx.warn(f'{self.entry.archive.path}: skipping update of {arcname}\n     using: {existing_entry.origin}\n  ignoring: {origin}')
                return None
            else:
                mx.logv(f'{self.entry.archive.path}: replacing contents of {arcname}\n  replacing: {existing_entry.origin}\n       with: {origin}')
        self._can_write = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._can_write:
            if exists(self.entry.staged):
                self.entries[self.entry.name] = self.entry

class _ArchiveStager(object):
    """
    Object used to create and populate the staging directory for a distribution's archive(s).
    """

    # Pattern for a versioned META-INF directory
    versioned_meta_inf_re = re.compile(r'META-INF/versions/([1-9][0-9]*)/META-INF/')

    def __init__(self, bin_archive, src_archive, exploded):
        """
        :param JARDistribution dist: the distribution whose archive contents are being staged
        :param _Archive bin_archive: the distribution's binary archive
        :param _Archive src_archive: the distribution's source archive
        """
        self.dist = bin_archive.dist
        self.bin_archive = bin_archive
        self.src_archive = src_archive
        self.exploded = exploded

        self.services = {}
        self.manifest = self.dist.manifestEntries.copy()

        self.snippetsPattern = None
        if hasattr(self.dist.suite, 'snippetsPattern'):
            self.snippetsPattern = re.compile(self.dist.suite.snippetsPattern)

        # Map from overlays to the projects that define them
        self.overlays = {}
        self.stage_archive()

    def stage_archive(self):
        """
        Creates and populates the archive staging directories.
        For efficiency, symbolic links are used where possible.
        """

        dist = self.dist

        for a in dist.archiveparticipants:
            a.__opened__(self.bin_archive, self.src_archive, self.services)

        # Overlay projects whose JDK version is less than 9 must be processed before the overlayed projects
        # as the overlay classes must be added to the jar instead of the overlayed classes. Overlays for
        # JDK 9 or later use the multi-release jar layout.
        head = [d for d in dist.archived_deps() if d.isJavaProject() and (self.exploded or d.javaCompliance.value < 9) and hasattr(d, 'overlayTarget')]
        tail = [d for d in dist.archived_deps() if d not in head]

        mainClass = dist.mainClass
        if mainClass:
            if 'Main-Class' in self.manifest:
                mx.abort("Main-Class is defined both as the 'mainClass': '" + mainClass + "' argument and in 'manifestEntries' as "
                        + self.manifest['Main-Class'] + " of the " + dist.name + " distribution. There should be only one definition.")
            self.manifest['Main-Class'] = mainClass

        for dep in head + tail:
            self.stage_dep(dep)

        for a in dist.archiveparticipants:
            self.close_archiveparticipant(a)

        _accumulate_services(self.services)

        for service_or_version, providers in self.services.items():
            if isinstance(service_or_version, int):
                services_version = service_or_version
                for service, providers_ in sorted(providers.items()):
                    self.add_service_providers(service, providers_, 'META-INF/_versions/' + str(services_version) + '/')
            else:
                self.add_service_providers(service_or_version, providers)

        self.bin_archive.finalize_archive_or_directory(self.manifest)
        if self.bin_archive is not self.src_archive:
            self.src_archive.finalize_archive_or_directory(None)

    def close_archiveparticipant(self, a):
        """
        Closes the archive participant `a` just prior to finalizing the archive (see `_Archive.finalize_archive_or_directory`).
        """
        closing = getattr(a, '__closing__', None)
        if closing is not None:
            extra = a.__closing__()
            if extra:
                try:
                    bin_archive_extra, src_archive_extra = extra
                except (TypeError, ValueError) as e:
                    mx.abort(f'Value returned by __closing__ ({_source_pos(closing)}) must be None or a 2-tuple: {e}')

                def stage_extra(extra, archive):
                    if extra is None:
                        return
                    if not isinstance(extra, dict):
                        index = 0 if extra is bin_archive_extra else 1
                        mx.abort(f'Type of value {index} in tuple returned by __closing__ ({_source_pos(closing)}) must be None or a dict, not {extra.__class__.__name__}')
                    for arcname, content in extra.items():
                        self.add_contents(archive, arcname, content)

                stage_extra(bin_archive_extra, self.bin_archive)
                stage_extra(src_archive_extra, self.src_archive)

    def add_service_providers(self, service, providers, archive_prefix=''):
        arcname = archive_prefix + 'META-INF/services/' + service
        # Convert providers to a set before printing to remove duplicates
        contents = '\n'.join(sorted(frozenset(providers))) + '\n'
        self.add_contents(self.bin_archive, arcname, contents)

    def add_contents(self, archive, arcname, contents):
        """
        Creates a file at `arcname` under `archive.staging_dir` with the data in `contents`
        and adds an entry to `archive.entries`.
        """
        origin = _FileContentsSupplier(join(archive.staging_dir, arcname))
        entry = _ArchiveEntry(None, arcname, archive, origin)
        staged = entry.staged
        mx.ensure_dir_exists(dirname(staged))
        if callable(contents):
            contents = contents()
        with open(staged, 'w' if isinstance(contents, str) else 'wb') as fp:
            assert arcname not in archive.entries, (arcname, archive.path)
            fp.write(contents)
        archive.entries[arcname] = entry

    def add_jar(self, dep, jar_path, is_sources_jar=False):
        """
        Adds the contents of `jar_path` to the relevant staging directory.

        :param Dependency dep: the Dependency owning the jar file
        :param str jar_path: path to the jar file to be extracted
        :param is_sources_jar: False if the contents are to be extracted to the primary staging directory,
                            True if they should be extracted to the sources staging directory
        """
        jar_timestamp = mx.TimeStampFile(jar_path)
        archive = self.src_archive if is_sources_jar else self.bin_archive
        with zipfile.ZipFile(jar_path, 'r') as zf:
            for arcname in zf.namelist():
                if arcname.endswith('/'):
                    if not self.exploded:
                        # Use a self reference for a directory that needs an explicit entry in the archive
                        archive.entries[arcname] = arcname
                    continue
                if not is_sources_jar and arcname == 'module-info.class':
                    mx.logv(jar_path + ' contains ' + arcname + '. It will not be included in ' + self.bin_archive.path)
                    continue
                service = arcname[len('META-INF/services/'):]
                if not is_sources_jar and arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/' and '/' not in service:
                    # Note: do not treat subdirectories of META-INF/services in any special way and just copy them to
                    # the result as if they were just regular resource files. They are not part of the specification,
                    # but some libraries are known to use them for internal purposes.
                    # (e.g., the org.jline.terminal.spi.TerminalProvider class in JLine3).
                    self.services.setdefault(service, []).extend(zf.read(arcname).decode().splitlines())
                else:
                    entry = _ArchiveEntry(dep, arcname, archive, jar_path + '!' + arcname)
                    with _StagingGuard(entry) as guard:
                        if guard:
                            staged = entry.staged
                            if not exists(staged) or jar_timestamp.isNewerThan(staged):
                                zf.extract(arcname, entry.archive.staging_dir)
                            contents = _FileContentsSupplier(staged)
                            if not _process_archiveparticipants(self.dist, entry.archive, arcname, contents.get, staged, is_source=is_sources_jar):
                                if self.versioned_meta_inf_re.match(arcname):
                                    mx.warn(f"META-INF resources can not be versioned ({arcname} from {jar_path}). The resulting JAR will be invalid.")

    def add_file(self, dep, filepath, relpath, archivePrefix, arcnameCheck=None, includeServices=False):
        """
        Adds the contents of the file `filepath` to `self.bin_archive.staging_dir`
        under the path formed by concatenating `archivePrefix` with `relpath`.

        :param Dependency dep: the Dependency owning the file
        """
        arcname = join(archivePrefix, relpath).replace(os.sep, '/')
        assert arcname[-1] != '/'
        if arcnameCheck is not None and not arcnameCheck(arcname):
            return
        if relpath.startswith(join('META-INF', 'services')):
            if includeServices:
                service = basename(relpath)
                assert dirname(relpath) == join('META-INF', 'services')
                m = self.versioned_meta_inf_re.match(arcname)
                if m:
                    service_version = int(m.group(1))
                    services_dict = self.services.setdefault(service_version, {})
                else:
                    services_dict = self.services
                with mx.open(filepath, 'r') as fp:
                    services_dict.setdefault(service, []).extend([provider.strip() for provider in fp.readlines()])
        else:
            if self.snippetsPattern and self.snippetsPattern.match(relpath):
                return
            contents = _FileContentsSupplier(filepath)
            entry = _ArchiveEntry(dep, arcname, self.bin_archive, filepath)
            with _StagingGuard(entry) as guard:
                if guard:
                    staged = entry.staged
                    if not _process_archiveparticipants(self.dist, self.bin_archive, arcname, contents.get, staged):
                        self.stage_file(filepath, staged)
                        if self.versioned_meta_inf_re.match(arcname):
                            mx.warn(f"META-INF resources can not be versioned ({filepath}). The resulting JAR will be invalid.")

    def add_java_sources(self, dep, srcDir, archivePrefix='', arcnameCheck=None):
        """
        Adds the contents of the Java source files under `srcDir` to the sources archive staging directory.

        :param Dependency dep: the Dependency owning the Java sources
        """
        for root, _, files in os.walk(srcDir):
            relpath = root[len(srcDir) + 1:]
            for f in files:
                if f.endswith('.java'):
                    arcname = join(archivePrefix, relpath, f).replace(os.sep, '/')
                    if arcnameCheck is None or arcnameCheck(arcname):
                        contents = _FileContentsSupplier(join(root, f))
                        entry = _ArchiveEntry(dep, arcname, self.src_archive, contents.path)
                        with _StagingGuard(entry) as guard:
                            staged = entry.staged
                            if guard:
                                if not _process_archiveparticipants(self.dist, self.src_archive, arcname, contents.get, staged, is_source=True):
                                    self.stage_file(contents.path, staged)

    def stage_file(self, src, dst):
        _stage_file_impl(src, dst)

    def stage_dep(self, dep):
        """
        Copies or symlinks the content from `dep` into the appropriate staging directories.
        """
        dist = self.dist
        original_path = dist.original_path()

        if hasattr(dep, "doNotArchive") and dep.doNotArchive:
            mx.logv('[' + original_path + ': ignoring project ' + dep.name + ']')
            return
        if dist.theLicense is not None and set(dist.theLicense or []) < set(dep.theLicense or []):
            if dep.suite.getMxCompatibility().supportsLicenses() and dist.suite.getMxCompatibility().supportsLicenses():
                report = mx.abort
            else:
                report = mx.warn
            depLicense = [l.name for l in dep.theLicense] if dep.theLicense else ['??']
            selfLicense = [l.name for l in dist.theLicense] if dist.theLicense else ['??']
            report(f"Incompatible licenses: distribution {dist} ({', '.join(selfLicense)}) can not contain {dep} ({', '.join(depLicense)})")
        if dep.isLibrary() or dep.isJARDistribution():
            if dep.isLibrary():
                l = dep
                # optional libraries and their dependents should already have been removed
                assert not l.optional or l.is_available()
                # merge library jar into distribution jar
                mx.logv('[' + original_path + ': adding library ' + l.name + ']')
                jarPath = l.get_path(resolve=True)
                jarSourcePath = l.get_source_path(resolve=True)
            elif dep.isJARDistribution():
                mx.logv('[' + original_path + ': adding distribution ' + dep.name + ']')
                jarPath = dep.path
                jarSourcePath = dep.sourcesPath
            else:
                mx.abort(f'Dependency not supported: {dep.name} ({dep.__class__.__name__})')
            if jarPath:
                self.add_jar(dep, jarPath)
            if jarSourcePath:
                self.add_jar(dep, jarSourcePath, True)
        elif dep.isMavenProject():
            mx.logv('[' + original_path + ': adding jar from Maven project ' + dep.name + ']')
            self.add_jar(dep, dep.classpath_repr())
            for srcDir in dep.source_dirs():
                self.add_java_sources(dep, srcDir)
        elif dep.isJavaProject():
            p = dep
            javaCompliance = dist.maxJavaCompliance()
            if javaCompliance:
                if p.javaCompliance > javaCompliance:
                    mx.abort(f"Compliance level doesn't match: Distribution {dist} requires {javaCompliance}, but {p} is {p.javaCompliance}.", context=dist)

            mx.logv('[' + original_path + ': adding project ' + p.name + ']')
            outputDir = p.output_dir()

            archivePrefix = p.archive_prefix() if hasattr(p, 'archive_prefix') else ''
            mrjVersion = getattr(p, 'multiReleaseJarVersion', None)
            is_overlay = False
            if mrjVersion is not None:
                if p.javaCompliance.value < 9:
                    mx.abort('Project with "multiReleaseJarVersion" attribute must have javaCompliance >= 9', context=p)
                if archivePrefix:
                    mx.abort("Project cannot have a 'multiReleaseJarVersion' attribute if it has an 'archivePrefix' attribute", context=p)
                if self.exploded:
                    is_overlay = True
                else:
                    try:
                        mrjVersion = mx._parse_multireleasejar_version(mrjVersion)
                    except ArgumentTypeError as e:
                        mx.abort(str(e), context=p)
                    archivePrefix = f'META-INF/versions/{mrjVersion}/'
                    self.manifest['Multi-Release'] = 'true'
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
                    current_overlayer = self.overlays.get(arcname)
                    if current_overlayer:
                        if mrjVersion is None and getattr(p, 'multiReleaseJarVersion', current_overlayer) is None:
                            mx.abort(f'Overlay for {arcname} is defined by more than one project: {current_overlayer} and {p}')
                        else:
                            if current_overlayer.javaCompliance.highest_specified_value() > p.javaCompliance.highest_specified_value():
                                # Overlay from project with highest javaCompliance wins
                                return False
                    self.overlays[arcname] = p
                    return True
                else:
                    return arcname not in self.overlays

            def add_classes(archivePrefix, includeServices):
                for root, _, files in os.walk(outputDir):
                    reldir = root[len(outputDir) + 1:]
                    for f in files:
                        # If the directory contains a special file named .mxkeep then add a file entry for it
                        # This was added for the needs of https://github.com/oracle/graal/pull/4327
                        if f == ".mxkeep":
                            dirEntry = reldir.replace(os.sep, '/') + '/'
                            self.bin_archive.entries[dirEntry] = dirEntry
                        else:
                            relpath = join(reldir, f)
                            filepath = join(root, f)
                            self.add_file(dep, filepath, relpath, archivePrefix, arcnameCheck=overlay_check, includeServices=includeServices)

            add_classes(archivePrefix, includeServices=True)
            sourceDirs = p.source_dirs()
            if p.source_gen_dir():
                sourceDirs.append(p.source_gen_dir())
            for srcDir in sourceDirs:
                self.add_java_sources(dep, srcDir, archivePrefix, arcnameCheck=overlay_check)

            if not self.exploded and p.javaCompliance.value <= 8:
                for ver in p.javaCompliance._values():
                    if ver > 8:
                        # Make a multi-release-jar versioned copy of the class files
                        # if compliance includes 8 or less and a version higher than 8.
                        # Anything below that version will pick up the class files in the
                        # root directory of the jar.
                        if mx.get_jdk(str(mx.JavaCompliance(ver)), cancel='probing'):
                            archivePrefix = f'META-INF/versions/{ver}/'
                            add_classes(archivePrefix, includeServices=False)
                        break

        elif dep.isArchivableProject():
            mx.logv('[' + original_path + ': adding archivable project ' + dep.name + ']')
            archivePrefix = dep.archive_prefix()
            outputDir = dep.output_dir()
            for f in dep.getResults():
                relpath = dep.get_relpath(f, outputDir)
                self.add_file(dep, f, relpath, archivePrefix)
        elif dep.isLayoutDirDistribution():
            mx.logv('[' + original_path + ': adding contents of layout dir distribution ' + dep.name + ']')
            for file_path, arc_name in dep.getArchivableResults():
                self.add_file(dep, file_path, arc_name, '')
        elif dep.isClasspathDependency():
            mx.logv('[' + original_path + ': adding classpath ' + dep.name + ']')
            jarPath = dep.classpath_repr(resolve=True)
            self.add_jar(dep, jarPath)
        else:
            mx.abort(f'Dependency not supported: {dep.name} ({dep.__class__.__name__})')

class _FileContentsSupplier(object):
    def __init__(self, path, eager=False):
        self.path = path
        self.contents = None
        if eager:
            self.get()

    def get(self):
        if self.contents is None:
            with open(self.path, 'rb') as fp:
                self.contents = fp.read()
        return self.contents

    def restore(self):
        assert self.contents is not None, ('must create with eager=True:', self.path)
        with open(self.path, 'wb') as fp:
            fp.write(self.contents)

def _accumulate_services(services):
    """
    Process `services` such that the services for version N include
    all the services defined for all versions < N.

    :param services: a dict whose keys are either str or int.
           A str key is a service name and the value is a list of provider names.
           An int key is a Java major version and the value is itself a dict from
           service name to a list of service provider names.

           Example:

           { "Foo": [ "FooImpl" ],
             11: { "Bar": [ "BarImpl" ] }
             16: { "Baz": [ "BazImpl" ] }
           }

           becomes:

           { "Foo": [ "FooImpl" ],
             11: { "Foo": [ "FooImpl" ], "Bar": [ "BarImpl" ] },
             16: { "Foo": [ "FooImpl" ], "Bar": [ "BarImpl" ], "Baz": [ "BazImpl" ] }
           }
    """
    versions = sorted([v for v in services if isinstance(v, int)])
    if versions:
        # Initialize accumulated services with non-versioned services
        accummulated_services = {n: set(p) for n, p in services.items() if isinstance(n, str)}

        # Now accumulate and update services for each version
        for v in versions:
            for service, providers in services[v].items():
                accumulated_providers = accummulated_services.setdefault(service, set())
                accumulated_providers.update(providers)
                services[v][service] = list(accumulated_providers)

# Suffix added to a distributions archive path to create the staging directory for the archive
_staging_dir_suffix = '.files'

class _Archive(object):
    """
    The path to a distribution's archive and its staging directory as well as the metadata for
    entries in the staging directory.
    """
    def __init__(self, dist, path, exploded, compression):
        self.dist = dist
        self.path = path
        self.exploded = exploded
        self.staging_dir = path if exploded else mx.ensure_dir_exists(path + _staging_dir_suffix)
        self.entries = {} # Map from archive entry names to _ArchiveEntry objects
        self.compression = compression

    def clean(self):
        path = self.path
        exploded_marker = join(self.path, '.exploded')
        if self.exploded:
            # Clean non-exploded staging directory if it exists
            if exists(path + _staging_dir_suffix):
                mx.rmtree(path + _staging_dir_suffix)

            # Remove jar file if last build was not exploded
            if not exists(exploded_marker):
                if exists(path):
                    os.remove(path)
                os.mkdir(path)
                with open(exploded_marker, 'w'):
                    pass
            return

        # Not exploded
        if exists(path):
            # If last build was exploded, remove it completely
            if exists(exploded_marker):
                mx.rmtree(path)
            else:
                # Remove jar file
                os.remove(path)

    def finalize_archive_or_directory(self, manifest):
        """
        Creates the archive in `self.path` from the files in `self.staging_dir` or, if `exploded` is True,
        make `self.path` be equivalent to `self.staging_dir` either by symlinking or copying it.
        """
        self.finalize_staging_directory()

        manifest_contents = None
        if manifest:
            version = manifest.pop('Manifest-Version', '1.0')
            manifest_contents = 'Manifest-Version: ' + version + '\n'
            for manifestKey, manifestValue in manifest.items():
                manifest_contents = manifest_contents + manifestKey + ': ' + manifestValue + '\n'

        if self.exploded:
            # write manifest even if exploded other components may depend on it
            if manifest_contents:
                metainf = os.path.join(self.path, 'META-INF')
                os.makedirs(metainf, exist_ok=True)
                with open(os.path.join(metainf, 'MANIFEST.MF'), 'w') as f:
                    f.write(manifest_contents)
        else:
            with zipfile.ZipFile(self.path, 'w', compression=self.compression) as zf:
                if manifest_contents:
                    zf.writestr("META-INF/MANIFEST.MF", manifest_contents)

                # Add explicit archive entries for directories and
                # remove them from self.entries in the process
                new_entries = {}
                for name, entry in self.entries.items():
                    if name == entry:
                        assert entry.endswith('/'), entry
                        zf.writestr(entry, '')
                    else:
                        new_entries[name] = entry
                self.entries = new_entries

                for dirpath, _, filenames in os.walk(self.staging_dir):
                    for filename in filenames:
                        if filename == self.jdk_8268216:
                            # Do not include placeholder file
                            continue
                        filepath = join(dirpath, filename)
                        arcname = filepath[len(self.staging_dir) + 1:]
                        with open(filepath, 'rb') as fp:
                            contents = fp.read()
                        info = zipfile.ZipInfo(arcname, time.localtime(os.path.getmtime(filepath))[:6])
                        info.compress_type = self.compression
                        info.external_attr = S_IMODE(os.stat(filepath).st_mode) << 16
                        zf.writestr(info, contents)

    # Name of non-symlink dummy file required workaround JDK-8267583 and JDK-8268216.
    jdk_8268216 = 'JDK_8268216'

    @staticmethod
    def create_jdk_8268216(dirpath):
        filepath = join(dirpath, _Archive.jdk_8268216)
        with open(filepath, 'w'):
            pass
        return filepath

    def finalize_staging_directory(self):
        """
        Deletes all stale entries under `self.staging_dir` and applies workaround for JDK-8267583 and JDK-8268216.
        These bugs force the requirement of at least one non-symlinked file in an non-empty directory.
        """

        # Maps a directory to the staged files it contains
        staged_dir_files = {}

        for name, entry in self.entries.items():
            if name == entry:
                # Entry for a directory
                continue
            staged_dir = dirname(entry.staged)
            staged_dir_files.setdefault(staged_dir, set()).add(basename(entry.staged))

        for dirpath, dirnames, filenames in os.walk(self.staging_dir, topdown=False):
            staged_files = staged_dir_files.get(dirpath)
            if staged_files:
                has_jdk_8268216 = False
                for filename in filenames:
                    if filename not in staged_files:
                        if filename == self.jdk_8268216:
                            has_jdk_8268216 = True
                        else:
                            os.remove(join(dirpath, filename))
                    else:
                        staged_files.remove(filename)
                assert not staged_files, staged_files

                if not has_jdk_8268216:
                    self.create_jdk_8268216(dirpath)
            elif not any((exists(join(dirpath, dirname)) for dirname in dirnames)):
                for filename in filenames:
                    os.remove(join(dirpath, filename))
                os.rmdir(dirpath)

    def __str__(self):
        return self.path

class _ArchiveEntry(object):
    """
    Describes the contents of an entry to be added to an archive.

    :param Dependency dep: the Dependency providing the contents or None
    :param str name: name of archive entry
    :param _Archive archive: archive containing entry
    :param str|callable origin: the file path from which the contents are read or a callable that generates the contents
    """
    def __init__(self, dep, name, archive, origin):
        self.dep = dep
        self.name = name
        self.archive = archive
        self.origin = origin
        relpath = self.name if os.sep == '/' else self.name.replace('/', os.sep)
        # absolute path to the staged contents of this entry.
        self.staged = join(self.archive.staging_dir, relpath)

    def origin_is_archive(self):
        if callable(self.origin):
            return False
        if '!' in self.origin:
            return True
        return False

    def resolve_origin_conflict(self, other):
        """
        Resolves a conflict between `self` and `other` which have different origins.

        :return: None if the contents of `self` and `other` are equal, `self` if
                 this entry's content takes precedence over `other`'s content,
                 otherwise `other`
        """
        assert isinstance(other, _ArchiveEntry) and other.name == self.name

        # Should never conflict on generated entries
        assert not callable(self.origin), self
        assert not callable(other.origin), other

        self_is_JavaProject = self.dep.isJavaProject()
        self_is_JARDistribution = self.dep.isJARDistribution()
        other_is_JavaProject = other.dep.isJavaProject()
        other_is_JARDistribution = other.dep.isJARDistribution()

        if self_is_JavaProject and other_is_JavaProject:
            # Select Java project with highest Java compliance
            if int(self.dep.javaCompliance.highest_specified_value()) > int(other.dep.javaCompliance.highest_specified_value()):
                return self
            else:
                return other

        # If self includes other or vice versa, there is no conflict
        if self_is_JavaProject and other_is_JARDistribution:
            if self.dep in other.dep.archived_deps():
                return None
        elif self_is_JARDistribution and other_is_JavaProject:
            if other.dep in self.dep.archived_deps():
                return None

        # Now try avoid reading complete contents if self and other are from zip files
        left, right = self.origin.split('!', 1), other.origin.split('!', 1)
        if len(left) == 2:
            # left is a zip file entry
            with zipfile.ZipFile(left[0]) as left_zf:
                left_info = left_zf.getinfo(left[1])
                if len(right) == 2:
                    # right is also a zip file entry
                    with zipfile.ZipFile(right[0]) as right_zf:
                        right_info = right_zf.getinfo(right[1])
                        # Avoid reading zip contents - the file size and CRC-32 should be
                        # sufficient for an equality comparison
                        if left_info.file_size == right_info.file_size and left_info.CRC == right_info.CRC:
                            return None
                else:
                    # right is a normal file
                    left = left_zf.read(left_info)
                    with open(right[0], 'rb') as fp:
                        right = fp.read()
                        if left == right:
                            return None
        else:
            # left is a normal file
            with open(left[0], 'rb') as fp:
                left = fp.read()
            if len(right) == 2:
                # right is a zip file
                with zipfile.ZipFile(right[0]) as right_zf:
                    right = right_zf.read(right[1])
            else:
                # right is a normal file
                with open(right[0], 'rb') as fp:
                    right = fp.read()
            if left == right:
                return None
        return self

    def __str__(self):
        return f'{self.dep}:{self.name}, origin={self.origin}, archive={self.archive}'

_build_exploded = None
def _use_exploded_build():
    """
    Gets (and caches) the value of the MX_BUILD_EXPLODED environment variable.

    If it is not "true" (i.e. not defined or defined to any other value), a distribution's archivable contents
    will be in a jar file located at `dist.path`. If the distribution defines a module, the jar will be updated to be a
    multi-release, modular jar and a jmod will be created that is compatible with the Java version corresponding in JAVA_HOME.

    If it is "true", a distribution's archivable contents will be in a directory located at `dist.path`.
    Since there's no support in Java for multi-release directories, there must be exactly one JDK specified
    by JAVA_HOME and EXTRA_JAVA_HOMES. If the distribution defines a module, the directory will be updated to be
    an exploded module compatible with the Java version corresponding in JAVA_HOME.

    :return bool: True iff the MX_BUILD_EXPLODED environment variable is "true"
    """
    global _build_exploded
    if _build_exploded is None:
        if mx.get_env('MX_BUILD_EXPLODED', None) == 'true':
            if mx._opts.strip_jars:
                mx.abort('MX_BUILD_EXPLODED=true is incompatible with --strip-jars')
            _build_exploded = True
        else:
            _build_exploded = False
    return _build_exploded

def _process_archiveparticipants(dist, archive, arcname, contents_supplier, staged, is_source=False):
    """
    Calls the __process__ method on `dist.archiveparticipants`, ensuring at most one participant claims
    responsibility for adding/omitting `contents` under the name `arcname` to/from the archive.

    :param str arcname: name in archive for `contents`
    :param str contents_supplier: a callable that returns a byte array to write to the archive under `arcname`
    :param str staged: path to file in which contents are staged. This will be deleted if it exists and a participant claims responsibility
    :return: True if a participant claimed responsibility, False otherwise

    """
    claimer = None
    for a in dist.archiveparticipants:
        if a.__process__(arcname, contents_supplier, is_source):
            if claimer:
                mx.abort('Archive participant ' + str(a) + ' cannot claim responsibility for ' + arcname + ' in ' +
                        archive.path + ' as it was already claimed by ' + str(claimer))
            claimer = a
    if claimer is None:
        return False
    if exists(staged):
        os.remove(staged)
    return True

def _patch_archiveparticipant(ap_type):
    """
    Adds an instance method named "__process__" to `ap_type` if it does not already define one.
    This method implements the protocol described by `JARDistribution.set_archiveparticipant`.
    """
    process = getattr(ap_type, '__process__', None)
    if process is None:

        def get_deprecated_method(name):
            """
            Gets the `name` method from `ap_type` if it exists and issue a warning about its deprecation.
            """
            method = getattr(ap_type, name, None)
            if method is not None:
                code = method.__code__
                protocol = JARDistribution.set_archiveparticipant.__code__
                mx.warn(f'The {name} method at {_source_pos(code)} is deprecated. See set_archiveparticipant at {_source_pos(protocol)}.')
            return method

        add = get_deprecated_method('__add__')
        addsrc = get_deprecated_method('__addsrc__')
        if add or addsrc:
            def process_impl(self, arcname, contents_supplier, is_source):
                if is_source:
                    return addsrc and addsrc(self, arcname, contents_supplier())
                return add and add(self, arcname, contents_supplier())
        else:
            def process_impl(self, arcname, contents_supplier, is_source):
                return False

        ap_type.__process__ = process_impl

def _source_pos(code):
    """
    Gets a string representing the file and source line at which `code` is declared.

    :param code: an object with ``co_filename`` and ``co_firstlineno`` fields
    """
    return f'{code.co_filename}:{code.co_firstlineno}'

def _stage_file_impl(src, dst):
    """
    Copies or symlinks `src` to `dst`.
    """
    # GR-36461: If the directories are the same, then nothing should be done.
    if not exists(src):
        return
    if exists(dst) and os.path.samefile(src, dst):
        return

    mx.ensure_dir_exists(dirname(dst))

    if not mx.can_symlink():
        if exists(dst):
            mx.rmtree(dst)
        if isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    else:
        if exists(dst):
            if islink(dst):
                target = os.readlink(dst)
                if target == src:
                    return
                if mx.is_windows() and target.startswith('\\\\?\\') and target[4:] == src:
                    # os.readlink was changed in python 3.8 to include a \\?\ prefix on Windows
                    return
            mx.rmtree(dst)
        elif islink(dst):
            # Remove a broken link
            os.remove(dst)
        os.symlink(src, dst)
